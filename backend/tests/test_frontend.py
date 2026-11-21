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


def test_start_page_is_checked_again_but_hashed_files_are_not(tmp_path: Path) -> None:
    # 12.09.2026: Die Startseite ging ohne Cache-Control hinaus. Nach einem Update behielt der
    # Browser die alte index.html, die auf Dateien zeigt, die es nicht mehr gibt: weisse Seite.
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text(INDEX, encoding="utf-8")
    (dist / "assets" / "app-1a2b3c.js").write_text("console.log(1)", encoding="utf-8")

    site = FastAPI()
    _mount_frontend(site, dist)
    client = TestClient(site)

    for page in ("/", "/kuenstler/abc", "/index.html"):
        assert client.get(page).headers.get("cache-control") == "no-cache", page
    # Der Name traegt die Pruefsumme des Inhalts, eine neue Fassung heisst anders.
    assert "no-cache" not in client.get("/assets/app-1a2b3c.js").headers.get("cache-control", "")


PUBLIC = Path(__file__).resolve().parents[2] / "frontend" / "public"


def test_every_file_of_public_is_asked_for_again(tmp_path: Path) -> None:
    # 21.11.2026: Dateien ohne Prüfsumme im Namen behielt der Browser nach einem Update, so blieb das alte Zeichen.
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text(INDEX, encoding="utf-8")
    files = [p.relative_to(PUBLIC).as_posix() for p in PUBLIC.rglob("*") if p.is_file()]
    assert "logo.svg" in files
    for name in files:
        (dist / name).parent.mkdir(parents=True, exist_ok=True)
        (dist / name).write_bytes((PUBLIC / name).read_bytes())
    site = FastAPI()
    _mount_frontend(site, dist)
    client = TestClient(site)
    for name in files:
        answer = client.get("/" + name)
        assert answer.status_code == 200 and answer.headers.get("cache-control") == "no-cache", name


def test_the_mark_follows_the_system_and_its_address_carries_a_version() -> None:
    mark = (PUBLIC / "logo.svg").read_text(encoding="utf-8")
    assert "@media (prefers-color-scheme: dark)" in mark and "#170b0d" in mark
    page = (PUBLIC.parent / "index.html").read_text(encoding="utf-8")
    assert 'href="/logo.svg?v=2"' in page
