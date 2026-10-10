"""The copied module is the module: every file as ``MANIFEST.json`` names it (Bauplan 05, "Gleichheit des gemeinsamen
Moduls"), and the app pins the libraries the module is built for. Runs in the app's own test run and CI, which see
only the app's repository. Red means: a file was changed in the app. Change it in ``bauplaene/oidc`` and copy it
again with ``tools/sync.py copy <app>``; never here."""

from __future__ import annotations

import base64
import hashlib
import importlib
import json
import re
from pathlib import Path
from typing import Any

import pytest


def _manifest(adapter: Any) -> tuple[Path, dict]:
    package = importlib.import_module(adapter.package)
    folder = Path(package.__file__).resolve().parent
    manifest = json.loads((folder / "MANIFEST.json").read_text(encoding="utf-8"))
    depth = len(Path(manifest["vendor_path"]).parts)
    return folder.parents[depth - 1], manifest


def _digest(path: Path) -> str:
    """``sha256-<base64>`` of the file with line ends as LF (a form the commit scanners pass, unlike 64 hex)."""
    raw = hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).digest()
    return "sha256-" + base64.b64encode(raw).decode("ascii")


def test_every_copied_file_equals_the_module(adapter: Any) -> None:
    root, manifest = _manifest(adapter)
    assert manifest["module"] == "oidc" and len(manifest["files"]) >= 20
    deviating = [
        name
        for name, expected in manifest["files"].items()
        if not (root / name).is_file() or _digest(root / name) != expected
    ]
    assert deviating == [], f"changed in the app instead of in bauplaene/oidc: {deviating}"


def test_the_copied_package_carries_the_version_of_the_manifest(adapter: Any) -> None:
    _, manifest = _manifest(adapter)
    package = importlib.import_module(adapter.package)
    assert package.__version__ == manifest["version"]


def test_the_app_pins_the_libraries_the_module_is_built_for(adapter: Any) -> None:
    root, manifest = _manifest(adapter)
    requirements = root / "backend" / "requirements.txt"
    if not requirements.is_file():
        pytest.fail(f"{requirements} is missing: the app must pin {manifest['requires']}")
    pins = {}
    for line in requirements.read_text(encoding="utf-8").splitlines():
        found = re.match(r"^\s*([A-Za-z0-9_.-]+)(?:\[[^\]]*\])?\s*==\s*([^\s;#]+)", line)
        if found:
            pins[found.group(1).lower()] = found.group(2)
    for name, wanted in manifest["requires"].items():
        assert pins.get(name) == wanted, (
            f"backend/requirements.txt pins {name}=={pins.get(name)}, the module needs {wanted}"
        )
