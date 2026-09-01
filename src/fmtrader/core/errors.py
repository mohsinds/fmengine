"""Core exception hierarchy (no fmtrader.* imports)."""


class FmtraderError(Exception):
    """Base error for the fmtrader package."""


class SettingsError(FmtraderError):
    """Raised when required configuration is missing or invalid."""
