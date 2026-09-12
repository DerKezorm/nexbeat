"""Mailtexte fuer Einladung, Passwort-Reset und Testmail, deutsch und englisch."""

from __future__ import annotations

from dataclasses import dataclass
from html import escape

APP_NAME = "nexbeat"


@dataclass(frozen=True)
class Mail:
    subject: str
    text: str
    html: str


_TEXTS: dict[str, dict[str, dict[str, str]]] = {
    "invitation": {
        "de": {
            "subject": "Einladung zu nexbeat",
            "heading": "Du bist eingeladen",
            "intro": "{inviter} hat dich zu nexbeat eingeladen. Dort entdeckst du neue Musik und fragst sie mit einem "
            "Klick an.",
            "action": "Einladung annehmen",
            "hint": "Der Link gilt sieben Tage und nur ein einziges Mal.",
        },
        "en": {
            "subject": "Your invitation to nexbeat",
            "heading": "You are invited",
            "intro": "{inviter} invited you to nexbeat. Discover new music there and request it with one click.",
            "action": "Accept invitation",
            "hint": "The link is valid for seven days and can be used once.",
        },
    },
    "password_reset": {
        "de": {
            "subject": "Neues Passwort fuer nexbeat",
            "heading": "Passwort zuruecksetzen",
            "intro": "Fuer dein Konto wurde ein neues Passwort angefordert.",
            "action": "Neues Passwort waehlen",
            "hint": "Der Link gilt eine Stunde. Hast du nichts angefordert, ignoriere diese Mail einfach.",
        },
        "en": {
            "subject": "New password for nexbeat",
            "heading": "Reset your password",
            "intro": "A new password was requested for your account.",
            "action": "Choose a new password",
            "hint": "The link is valid for one hour. If you did not ask for this, just ignore this mail.",
        },
    },
    "test": {
        "de": {
            "subject": "Testmail von nexbeat",
            "heading": "Der Mailversand funktioniert",
            "intro": "Diese Nachricht kam ueber den eingetragenen Mailserver. Einladungen und Passwort-Links "
            "koennen jetzt verschickt werden.",
            "action": "",
            "hint": "",
        },
        "en": {
            "subject": "Test mail from nexbeat",
            "heading": "Sending mail works",
            "intro": "This message went through the configured mail server. Invitations and password links can "
            "be sent now.",
            "action": "",
            "hint": "",
        },
    },
}


def _html(heading: str, intro: str, action: str, link: str, hint: str) -> str:
    button = ""
    if action and link:
        button = (
            f'<p style="margin:28px 0"><a href="{escape(link, quote=True)}" '
            'style="background:#e11d2f;color:#ffffff;text-decoration:none;padding:12px 22px;'
            f'border-radius:999px;font-weight:600;display:inline-block">{escape(action)}</a></p>'
            f'<p style="color:#9a9aa8;font-size:13px;word-break:break-all">{escape(link)}</p>'
        )
    hint_html = f'<p style="color:#9a9aa8;font-size:13px">{escape(hint)}</p>' if hint else ""
    return (
        '<div style="background:#0b0b0f;padding:32px 16px;font-family:Inter,Segoe UI,Arial,sans-serif">'
        '<div style="max-width:520px;margin:0 auto;background:#16161d;border:1px solid #26262f;'
        'border-radius:16px;padding:28px;color:#f2f2f5">'
        '<p style="font-weight:800;letter-spacing:.5px;margin:0 0 20px">NEX<span style="color:#e11d2f">BEAT</span></p>'
        f'<h1 style="font-size:22px;margin:0 0 12px">{escape(heading)}<span style="color:#e11d2f">.</span></h1>'
        f'<p style="color:#c3c3ce;line-height:1.6">{escape(intro)}</p>'
        f"{button}{hint_html}</div></div>"
    )


def render(kind: str, language: str, *, link: str = "", **values: str) -> Mail:
    texts = _TEXTS[kind].get(language) or _TEXTS[kind]["en"]
    intro = texts["intro"].format(**values)
    lines = [texts["heading"], "", intro]
    if texts["action"] and link:
        lines += ["", f"{texts['action']}: {link}"]
    if texts["hint"]:
        lines += ["", texts["hint"]]
    return Mail(
        subject=texts["subject"],
        text="\n".join(lines),
        html=_html(texts["heading"], intro, texts["action"], link, texts["hint"]),
    )
