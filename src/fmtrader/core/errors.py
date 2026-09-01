"""Core exception hierarchy (no fmtrader.* imports)."""


class FmtraderError(Exception):
    """Base error for the fmtrader package."""


class SettingsError(FmtraderError):
    """Raised when required configuration is missing or invalid."""


class ContractError(FmtraderError):
    """Raised when a domain contract (e.g. Bar) is violated."""


class DataError(FmtraderError):
    """Raised for data-layer failures (adapter, quality, catalog)."""


class QualityError(DataError):
    """Raised when the quality gate hard-fails structural checks."""


class AdapterError(DataError):
    """Raised when a vendor adapter cannot parse or declare capabilities."""


class FeatureError(FmtraderError):
    """Raised for feature/indicator/labeling failures (capability, lookback, YAML)."""


class BacktestError(FmtraderError):
    """Raised for backtest/cost/strategy execution failures."""
