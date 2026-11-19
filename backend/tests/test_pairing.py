"""Ein Geraet per Code verbinden: anfragen, im Browser bestaetigen, Token einmal abholen."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db import SessionLocal
from app.models import ApiKey, PairingRequest, utcnow
from app.services import api_keys, pairing
from tests.conftest import auth_headers, create_user


def _ask(client: TestClient, name: str | None = "nextune") -> dict[str, Any]:
    response = client.post("/api/pairing/request", json={"device_name": name}, headers={"Authorization": ""})
    assert response.status_code == 201, response.text
    return response.json()


def _poll(client: TestClient, made: dict[str, Any], secret: str | None = None) -> Any:
    return client.get(f"/api/pairing/request/{made['id']}",
                      headers={"X-Pairing-Secret": secret or made["secret"], "Authorization": ""})


def test_a_device_gets_a_token_once_after_the_code_is_confirmed(client: TestClient) -> None:
    create_user("lena")
    browser = auth_headers(client, "lena")
    made = _ask(client)
    assert len(made["code"]) == 9 and made["code"][4] == "-"
    assert _poll(client, made).json() == {"state": "waiting"}

    confirmed = client.post("/api/pairing/confirm", json={"code": made["code"].lower().replace("-", " ")}, headers=browser)
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json() == {"device_name": "nextune"}

    answer = _poll(client, made).json()
    assert answer["state"] == "confirmed"
    assert answer["account"] == {"name": "lena"}
    token = answer["token"]
    assert token.startswith(api_keys.PREFIX)
    # The token works like any API token of the account and may write (wishes).
    me = client.get("/api/v1/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200 and "request" in me.json()["may"]
    with SessionLocal() as db:
        key = db.scalars(select(ApiKey)).one()
        assert key.name == "nextune" and not key.read_only
        assert token not in (key.token_hash, key.preview)

    # Only once: the second question hears "used", and no second token appears.
    again = _poll(client, made)
    assert again.status_code == 410 and again.json()["detail"]["code"] == "pairing_used"
    with SessionLocal() as db:
        assert len(db.scalars(select(ApiKey)).all()) == 1


def test_the_secret_is_needed_and_never_stored(client: TestClient) -> None:
    made = _ask(client)
    wrong = _poll(client, made, secret="not-the-secret")
    assert wrong.status_code == 404 and wrong.json()["detail"]["code"] == "pairing_unknown"
    unknown = client.get("/api/pairing/request/nothing-here", headers={"X-Pairing-Secret": made["secret"]})
    assert unknown.status_code == 404
    with SessionLocal() as db:
        row = db.get(PairingRequest, made["id"])
        assert row is not None and made["secret"] not in row.secret_hash


def test_confirming_needs_a_browser_session_not_a_token(client: TestClient) -> None:
    user_id = create_user("lena")
    with SessionLocal() as db:
        from app.models import User

        _key, token = api_keys.create(db, db.get(User, user_id), name="script", read_only=False)
    made = _ask(client)
    refused = client.post("/api/pairing/confirm", json={"code": made["code"]}, headers={"Authorization": f"Bearer {token}"})
    assert refused.status_code == 403 and refused.json()["detail"]["code"] == "api_key_not_here"
    anonymous = client.post("/api/pairing/confirm", json={"code": made["code"]}, headers={"Authorization": ""})
    assert anonymous.status_code == 401


def test_wrong_codes_are_braked_per_account(client: TestClient) -> None:
    create_user("lena")
    browser = auth_headers(client, "lena")
    made = _ask(client)
    for _ in range(3):
        wrong = client.post("/api/pairing/confirm", json={"code": "AAAA-AAAA"}, headers=browser)
        assert wrong.status_code == 404 and wrong.json()["detail"]["code"] == "pairing_unknown"
    wrong = client.post("/api/pairing/confirm", json={"code": "AAAA-AAAA"}, headers=browser)
    assert wrong.status_code == 404
    braked = client.post("/api/pairing/confirm", json={"code": made["code"]}, headers=browser)
    assert braked.status_code == 429 and braked.json()["detail"]["code"] == "pairing_wait"
    assert "Retry-After" in braked.headers


def test_text_that_cannot_be_a_code_counts_for_nothing(client: TestClient) -> None:
    create_user("lena")
    browser = auth_headers(client, "lena")
    for text in ("ABC", "ABCD-EFG0", "ABCD-EFGI"):
        answer = client.post("/api/pairing/confirm", json={"code": text}, headers=browser)
        assert answer.status_code == 422 and answer.json()["detail"]["code"] == "pairing_code"
    made = _ask(client)
    assert client.post("/api/pairing/confirm", json={"code": made["code"]}, headers=browser).status_code == 200


def test_an_expired_code_cannot_be_confirmed_and_the_device_hears_it(client: TestClient) -> None:
    create_user("lena")
    browser = auth_headers(client, "lena")
    made = _ask(client)
    with SessionLocal() as db:
        row = db.get(PairingRequest, made["id"])
        row.expires_at = utcnow() - timedelta(seconds=1)
        db.commit()
    assert client.post("/api/pairing/confirm", json={"code": made["code"]}, headers=browser).status_code == 404
    gone = _poll(client, made)
    assert gone.status_code == 410 and gone.json()["detail"]["code"] == "pairing_expired"


def test_a_device_can_let_its_code_go(client: TestClient) -> None:
    create_user("lena")
    browser = auth_headers(client, "lena")
    made = _ask(client)
    gone = client.delete(f"/api/pairing/request/{made['id']}", headers={"X-Pairing-Secret": made["secret"]})
    assert gone.status_code == 204
    assert client.post("/api/pairing/confirm", json={"code": made["code"]}, headers=browser).status_code == 404


def test_a_full_account_is_told_before_anything_happens(client: TestClient) -> None:
    user_id = create_user("lena")
    browser = auth_headers(client, "lena")
    with SessionLocal() as db:
        from app.models import User

        user = db.get(User, user_id)
        for i in range(api_keys.MOST):
            api_keys.create(db, user, name=f"key {i}", read_only=True)
    made = _ask(client)
    full = client.post("/api/pairing/confirm", json={"code": made["code"]}, headers=browser)
    assert full.status_code == 409 and full.json()["detail"]["code"] == "api_key_too_many"
    assert _poll(client, made).json() == {"state": "waiting"}


def test_open_requests_are_limited_so_nobody_floods_the_table(client: TestClient) -> None:
    for _ in range(pairing.MOST_OPEN):
        _ask(client)
    busy = client.post("/api/pairing/request", json={}, headers={"Authorization": ""})
    assert busy.status_code == 429 and busy.json()["detail"]["code"] == "pairing_busy"


def test_codes_avoid_letters_that_look_alike(client: TestClient) -> None:
    for _ in range(20):
        code = _ask(client, name=None)["code"].replace("-", "")
        assert not set(code) & set("0O1IL")
