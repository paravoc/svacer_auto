"""Tests for custom exception hierarchy"""
from svacer_mcp.exceptions import (
    SvacerError,
    SvacerAuthError,
    SvacerAPIError,
    SvacerConfigError,
    SvacerValidationError,
)


def test_hierarchy():
    assert issubclass(SvacerAuthError, SvacerError)
    assert issubclass(SvacerAPIError, SvacerError)
    assert issubclass(SvacerConfigError, SvacerError)
    assert issubclass(SvacerValidationError, SvacerError)


def test_svacererror_is_exception():
    assert issubclass(SvacerError, Exception)


def test_catch_all_svacer_errors():
    for exc_cls in (SvacerAuthError, SvacerAPIError, SvacerConfigError, SvacerValidationError):
        try:
            raise exc_cls("test")
        except SvacerError as e:
            assert str(e) == "test"
