"""
Input validation utilities for Svacer MCP tools
"""
from uuid import UUID


def is_valid_uuid(value: str) -> bool:
    """Return True if *value* is a canonical UUID string (any version, e.g. v4 or v7).

    Accepts the 8-4-4-4-12 hex form, case-insensitive. Rejects no-dashes,
    braced, and ``urn:uuid:`` variants — Svacer URLs need the canonical form.
    """
    if not isinstance(value, str):
        return False
    try:
        return str(UUID(value)) == value.lower()
    except ValueError:
        return False


def validate_uuid(value: str, name: str = "id") -> None:
    """Raise ValueError if *value* is not a canonical UUID string."""
    if not is_valid_uuid(value):
        raise ValueError(f"{name} is not a valid UUID: {value!r}")
