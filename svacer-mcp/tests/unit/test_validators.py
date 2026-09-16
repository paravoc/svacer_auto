"""Tests for UUID validation utilities"""
import pytest
from svacer_mcp.utils.validators import is_valid_uuid, validate_uuid


class TestIsValidUuid:
    def test_valid_uuid_v4(self):
        assert is_valid_uuid("550e8400-e29b-41d4-a716-446655440000")

    def test_valid_uuid_v7(self):
        # version 7: 13th nibble is "7"
        assert is_valid_uuid("01890b96-7c5e-7000-8000-000000000000")

    def test_valid_uuid_uppercase(self):
        assert is_valid_uuid("550E8400-E29B-41D4-A716-446655440000")

    def test_invalid_too_short(self):
        assert not is_valid_uuid("550e8400")

    def test_invalid_no_dashes(self):
        # uuid.UUID accepts no-dashes form, but Svacer URLs need canonical 8-4-4-4-12
        assert not is_valid_uuid("550e8400e29b41d4a716446655440000")

    def test_invalid_braces(self):
        assert not is_valid_uuid("{550e8400-e29b-41d4-a716-446655440000}")

    def test_invalid_urn_prefix(self):
        assert not is_valid_uuid("urn:uuid:550e8400-e29b-41d4-a716-446655440000")

    def test_invalid_empty(self):
        assert not is_valid_uuid("")

    def test_invalid_random_string(self):
        assert not is_valid_uuid("not-a-uuid-at-all")

    def test_invalid_special_chars(self):
        assert not is_valid_uuid("550e8400-e29b-41d4-a716-44665544000g")

    def test_invalid_non_string(self):
        assert not is_valid_uuid(None)  # type: ignore[arg-type]


class TestValidateUuid:
    def test_valid_passes(self):
        validate_uuid("550e8400-e29b-41d4-a716-446655440000", "test_id")

    def test_invalid_raises_value_error(self):
        with pytest.raises(ValueError, match="project_id"):
            validate_uuid("bad-uuid", "project_id")

    def test_error_message_contains_value(self):
        with pytest.raises(ValueError, match="bad-value"):
            validate_uuid("bad-value", "field")
