"""Loads the app's adapter (``backend/tests/nexoidc_adapter.py``, or the file named by ``NEXOIDC_ADAPTER``) and gives
every contract test a fresh app, the vendored package and a fake network. Copied unchanged into every app."""

from __future__ import annotations

import importlib
import importlib.util
import os
import sys
from collections.abc import Iterator
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

# Imported by name after the path is set: a plain import statement here would sit below code, which some apps
# flag (E402) and others would flag a suppression for (RUF100).
fakes = importlib.import_module("oidc_fakes")


def _adapter_module() -> ModuleType:
    path = Path(os.environ.get("NEXOIDC_ADAPTER") or HERE.parent / "nexoidc_adapter.py")
    if not path.is_file():
        raise RuntimeError(
            f"the contract tests need the app's adapter at {path} (template: tests-fuer-apps/adapter_template.py)"
        )
    spec = importlib.util.spec_from_file_location("nexoidc_adapter", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["nexoidc_adapter"] = module
    spec.loader.exec_module(module)
    return module


ADAPTER = _adapter_module()


@pytest.fixture
def adapter() -> Iterator[Any]:
    adapter = ADAPTER.Adapter()
    adapter.start()
    package = oidc_package(adapter)
    package.protocol.clear_caches()
    package.attempt.forget_used_states()
    try:
        yield adapter
    finally:
        package.use_transport(None)
        package.protocol.clear_caches()
        package.attempt.forget_used_states()
        adapter.stop()


def oidc_package(adapter: Any) -> ModuleType:
    package = importlib.import_module(adapter.package)
    for name in ("protocol", "attempt", "flow", "accounts", "providers", "authentik", "migrate", "coupling"):
        importlib.import_module(f"{adapter.package}.{name}")
    return package


@pytest.fixture
def oidc(adapter: Any) -> ModuleType:
    return oidc_package(adapter)


@pytest.fixture
def net(oidc: ModuleType) -> Iterator[fakes.Network]:
    network = fakes.Network()
    oidc.use_transport(network.transport())
    yield network
    oidc.use_transport(None)


@pytest.fixture
def sso(net: fakes.Network) -> fakes.FakeProvider:
    return net.add(fakes.FakeProvider())


@pytest.fixture
def with_sso(adapter: Any, sso: fakes.FakeProvider) -> dict[str, Any]:
    """The fake provider as the entry ``sso``."""
    if adapter.only_authentik:
        return add_in_store(adapter, sso, "sso")
    response = adapter.add_provider(sso, slug="sso")
    assert response.status_code in (200, 201), response.text
    return response.json()


def add_in_store(app: Any, fake: fakes.FakeProvider, slug: str, **values: Any) -> dict[str, Any]:
    """An entry written straight into the store (for apps whose form takes no second entry)."""
    package = oidc_package(app)
    with app.store() as store:
        position = len(store.list_providers())
        created = store.insert_provider(
            package.ProviderValues(
                slug=slug,
                label=values.get("label", "SSO"),
                issuer=str(values.get("issuer", fake.issuer)).rstrip("/"),
                client_id=fake.client_id,
                client_secret=fake.client_secret,
                scopes=package.DEFAULT_SCOPES,
                enabled=True,
                auto_create=values.get("auto_create", False),
                trusts_second_factor=values.get("trusts_second_factor", True),
                managed=values.get("managed", ""),
                position=position,
            )
        )
        store.commit()
    return {"id": created.id, "slug": created.slug}
