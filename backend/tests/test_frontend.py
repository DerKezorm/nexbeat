"""Das gebaute Frontend hinter FastAPI: Seiten, Dateien, unbekannte API-Pfade."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.main import _mount_frontend

INDEX = '<div id="root"></div>'


def test_built_frontend_is_served(tmp_path: Path) -> None:
    # 11.09.2026: Mit gebautem Frontend startete das Backend nicht. Die Tests liefen
    # ohne dist und sahen den Fehler nie.
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text(INDEX, encoding="utf-8")
    (dist / "assets" / "app.js").write_text("console.log(1)", encoding="utf-8")
    (dist / "logo.svg").write_text("<svg/>", encoding="utf-8")
    (tmp_path / "secret.txt").write_text("outside", encoding="utf-8")

    site = FastAPI()
    _mount_frontend(site, dist)
    client = TestClient(site)

    assert client.get("/assets/app.js").text == "console.log(1)"
    assert client.get("/logo.svg").text == "<svg/>"
    assert client.get("/").text == INDEX
    assert client.get("/kuenstler/abc").text == INDEX

    missing = client.get("/api/nothing")
    assert missing.status_code == 404
    assert "not_found" in missing.text

    # Nichts ausserhalb des Ordners, auch nicht ueber kodierte Punkte.
    assert client.get("/%2e%2e/secret.txt").text == INDEX
