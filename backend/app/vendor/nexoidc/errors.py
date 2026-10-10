"""The fixed error codes (Bauplan 02, "Fehlercodes"). Every app uses exactly these; each has a sentence in German and
English in the module's wording files under ``oidc.error.<code>``.

A refused sign-in ends on the sign-in page with ``?error=<code>`` (a refused linking on the account page). The
message of an ``OidcError`` is English and meant for the log, never for the page.
"""

from __future__ import annotations

#: In the order of Bauplan 02.
CODES = (
    "oidc_not_configured",
    "oidc_provider_unreachable",
    "oidc_provider_invalid",
    "oidc_issuer_mismatch",
    "oidc_state_mismatch",
    "oidc_provider_error",
    "oidc_token_refused",
    "oidc_token_invalid",
    "oidc_no_signing_key",
    "oidc_no_account",
    "oidc_subject_taken",
    "oidc_only_account",
    "oidc_link_mismatch",
    "invite_invalid",
    "account_blocked",
    "too_many_attempts",
)

#: Problems with what the operator typed into the provider form. They belong to a field, not to a sign-in.
FORM_CODES = (
    "slug_invalid",
    "slug_taken",
    "label_required",
    "issuer_invalid",
    "client_id_required",
    "client_secret_invalid",
    "scopes_invalid",
    "provider_managed",
    "provider_unknown",
)


class OidcError(Exception):
    """A sign-in, a linking or a provider check failed. ``code`` is one of ``CODES``."""

    def __init__(self, code: str, message: str) -> None:
        if code not in CODES:
            raise ValueError(f"unknown OIDC error code {code!r}")
        super().__init__(message)
        self.code = code
        self.message = message


class ProviderInvalid(Exception):
    """The provider form cannot be saved. ``field`` names the field, ``code`` is one of ``FORM_CODES`` or, for the
    issuer, one of the discovery codes (``oidc_issuer_mismatch``, ``oidc_provider_unreachable``,
    ``oidc_provider_invalid``)."""

    def __init__(self, field: str, code: str, message: str) -> None:
        if code not in FORM_CODES and code not in CODES:
            raise ValueError(f"unknown form code {code!r}")
        super().__init__(message)
        self.field = field
        self.code = code
        self.message = message
