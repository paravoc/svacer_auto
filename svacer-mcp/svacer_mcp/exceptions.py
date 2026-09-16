"""
Custom exceptions for Svacer MCP Connector
"""


class SvacerError(Exception):
    """Base exception for all Svacer-related errors"""


class SvacerAuthError(SvacerError):
    """Authentication failed (bad credentials, server unreachable, etc.)"""


class SvacerAPIError(SvacerError):
    """Svacer API returned an error or unexpected response"""


class SvacerConfigError(SvacerError):
    """Configuration is invalid or incomplete"""


class SvacerValidationError(SvacerError):
    """Input validation failed (e.g. invalid UUID format)"""
