"""Core domain enumerations (no fmtrader.* imports)."""

from enum import StrEnum


class InstrumentClass(StrEnum):
    """Canonical instrument classification for the Bar contract."""

    SPOT_CFD = "spot_cfd"
    FUTURES_RAW = "futures_raw"
    FUTURES_CONTINUOUS = "futures_continuous"
    EQUITY = "equity"
    CRYPTO = "crypto"


class Side(StrEnum):
    """Quote side for vendor adapters that split bid/ask feeds."""

    BID = "bid"
    ASK = "ask"
    MID = "mid"
