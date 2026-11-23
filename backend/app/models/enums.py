"""Shared domain enums persisted as constrained strings."""

from enum import StrEnum


class UserRole(StrEnum):
    """Supported authorization roles."""

    ADMIN = "ADMIN"
    INVESTIGATOR = "INVESTIGATOR"
    ANALYST = "ANALYST"


class FindingStatus(StrEnum):
    """Lifecycle states for persisted investigative findings."""

    NEW = "NEW"
    REVIEWING = "REVIEWING"
    RESOLVED = "RESOLVED"
    DISMISSED = "DISMISSED"
