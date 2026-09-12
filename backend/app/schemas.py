"""Ein- und Ausgabeformen der API."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from .models import Role

USERNAME_PATTERN = r"^[A-Za-z0-9._-]{3,32}$"
MIN_PASSWORD_LENGTH = 8
MAX_PASSWORD_LENGTH = 128
LANGUAGES = ("de", "en")


class TokenPair(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int


class LoginIn(BaseModel):
    login: str = Field(min_length=1, max_length=255)
    password: str = Field(min_length=1, max_length=MAX_PASSWORD_LENGTH)


class SetupIn(BaseModel):
    username: str = Field(pattern=USERNAME_PATTERN)
    email: str = Field(min_length=3, max_length=255)
    password: str = Field(min_length=MIN_PASSWORD_LENGTH, max_length=MAX_PASSWORD_LENGTH)
    language: Literal["de", "en"] = "de"


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    email: str
    role: Role
    display_name: str
    language: str
    is_active: bool
    requires_approval: bool
    quota_limit: int | None
    created_at: datetime
    last_login_at: datetime | None


class QuotaOut(BaseModel):
    limit: int | None
    used: int
    remaining: int | None
    period: str
    resets_at: datetime


class MeOut(UserOut):
    is_admin: bool
    quota: QuotaOut


class AdminUserOut(UserOut):
    quota: QuotaOut


class MeUpdate(BaseModel):
    display_name: str | None = Field(default=None, max_length=128)
    language: Literal["", "de", "en"] | None = None


class PasswordChangeIn(BaseModel):
    current_password: str = Field(min_length=1, max_length=MAX_PASSWORD_LENGTH)
    new_password: str = Field(min_length=MIN_PASSWORD_LENGTH, max_length=MAX_PASSWORD_LENGTH)


class UserUpdate(BaseModel):
    role: Role | None = None
    is_active: bool | None = None
    requires_approval: bool | None = None
    display_name: str | None = Field(default=None, max_length=128)
    # Zahl, "default" (Vorgabe der Installation) oder "unlimited".
    quota: int | Literal["default", "unlimited"] | None = None


class InvitationIn(BaseModel):
    email: str = Field(min_length=3, max_length=255)
    role: Role = Role.user


class InvitationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: str
    role: Role
    created_at: datetime
    expires_at: datetime


class DeliveryOut(BaseModel):
    sent: bool
    manual_link: str | None = None
    error_code: str | None = None


class InvitationCreatedOut(BaseModel):
    invitation: InvitationOut
    delivery: DeliveryOut


class InvitationInfo(BaseModel):
    email: str
    role: Role


class AcceptInvitationIn(BaseModel):
    username: str = Field(pattern=USERNAME_PATTERN)
    password: str = Field(min_length=MIN_PASSWORD_LENGTH, max_length=MAX_PASSWORD_LENGTH)
    display_name: str = Field(default="", max_length=128)
    language: Literal["", "de", "en"] = ""


class ForgotPasswordIn(BaseModel):
    email: str = Field(min_length=3, max_length=255)


class ResetPasswordIn(BaseModel):
    password: str = Field(min_length=MIN_PASSWORD_LENGTH, max_length=MAX_PASSWORD_LENGTH)


class TestMailIn(BaseModel):
    to: str | None = Field(default=None, max_length=255)
