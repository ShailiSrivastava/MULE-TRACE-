"""Authentication and user response schemas."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, SecretStr, field_validator

from app.models.enums import UserRole
from app.security.passwords import validate_password


def _normalize_email(value: EmailStr) -> str:
    return str(value).strip().casefold()


class RegisterRequest(BaseModel):
    email: EmailStr
    password: SecretStr
    display_name: str | None = None

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: EmailStr) -> str:
        return _normalize_email(value)

    @field_validator("password")
    @classmethod
    def validate_new_password(cls, value: SecretStr) -> SecretStr:
        validate_password(value.get_secret_value())
        return value

    @field_validator("display_name")
    @classmethod
    def normalize_display_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("Display name cannot be blank.")
        return normalized


class LoginRequest(BaseModel):
    email: EmailStr
    password: SecretStr

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: EmailStr) -> str:
        return _normalize_email(value)

    @field_validator("password")
    @classmethod
    def validate_password_bounds(cls, value: SecretStr) -> SecretStr:
        if not value.get_secret_value() or len(value.get_secret_value()) > 128:
            raise ValueError("Password is invalid.")
        return value


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    email: EmailStr
    display_name: str | None
    role: UserRole
    is_active: bool
    created_at: datetime


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int


class ActivationUpdate(BaseModel):
    is_active: bool


class RoleUpdate(BaseModel):
    role: UserRole
