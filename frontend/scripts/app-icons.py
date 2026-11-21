"""The icons for the home screen, rendered once from the light version of the mark.

    python frontend/scripts/app-icons.py

Same shape as components/Logo.tsx and public/logo.svg; the source of every version is nexapps/icons-vergleich/neu.py.
Rendered with Playwright for Python (Chromium without a window).

The maskable icon is cropped by Android, so the mark sits smaller on a full white square. The Apple touch icon is full
bleed and without transparency: iOS rounds it itself.
"""

from __future__ import annotations

import io
from pathlib import Path

from PIL import Image
from playwright.sync_api import sync_playwright

PUBLIC = Path(__file__).resolve().parent.parent / "public"

VERLAUF = """<defs><linearGradient id="g" gradientUnits="userSpaceOnUse" x1="10" y1="10" x2="54" y2="54">
  <stop offset="0" stop-color="#ff8a95"/><stop offset=".5" stop-color="#e11d2f"/><stop offset="1" stop-color="#8f0f1c"/>
</linearGradient></defs>"""
ZEICHEN = """<path d="M10 33h9l4.5-11 7 22 6.5-17 4 6H54" fill="none" stroke="url(#g)" stroke-width="4.4" stroke-linecap="round"
  stroke-linejoin="round"/><path d="M23.5 22 30.5 44" stroke="#d90f25" stroke-width="4.4" stroke-linecap="round"/>
  <circle cx="54" cy="33" r="3.6" fill="#d90f25" stroke="#fff" stroke-width="1.8"/>"""


def kachel(s: int) -> str:
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64" width="{s}" height="{s}">{VERLAUF}'
            '<rect x="2" y="2" width="60" height="60" rx="16" fill="#fff"/>'
            '<rect x="2.75" y="2.75" width="58.5" height="58.5" rx="15.3" fill="none" stroke="#e11d2f" stroke-opacity=".3" '
            f'stroke-width="1.5"/>{ZEICHEN}</svg>')


def voll(s: int, m: float) -> str:
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64" width="{s}" height="{s}">{VERLAUF}'
            f'<rect width="64" height="64" fill="#fff"/><g transform="translate(32 32) scale({m}) translate(-32 -33)">{ZEICHEN}</g></svg>')


def randlos(s: int) -> str:
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="2 2 60 60" width="{s}" height="{s}">{VERLAUF}'
            f'<rect x="2" y="2" width="60" height="60" fill="#fff"/>{ZEICHEN}</svg>')


BILDER = [
    ("icon-192.png", kachel(192), 192, False),
    ("icon-512.png", kachel(512), 512, False),
    ("icon-maskable-512.png", voll(512, 0.82), 512, True),
    ("apple-touch-icon.png", randlos(180), 180, True),
]


def main() -> None:
    with sync_playwright() as p:
        browser = p.chromium.launch()
        for name, svg, size, opaque in BILDER:
            page = browser.new_page(viewport={"width": size, "height": size})
            page.set_content(f'<body style="margin:0;background:transparent">{svg}</body>')
            bild = Image.open(io.BytesIO(page.locator("svg").screenshot(omit_background=True)))
            page.close()
            assert bild.size == (size, size), (name, bild.size)
            (bild.convert("RGB") if opaque else bild.convert("RGBA")).save(PUBLIC / name, optimize=True)
            print("written:", PUBLIC / name)
        browser.close()


if __name__ == "__main__":
    main()
