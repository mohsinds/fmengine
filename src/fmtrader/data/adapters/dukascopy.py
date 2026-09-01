"""Dukascopy CSV adapter (epoch-ms OHLC, optional side tagging)."""

from __future__ import annotations

from pathlib import Path

import polars as pl

from fmtrader.core.enums import InstrumentClass, Side
from fmtrader.core.errors import AdapterError
from fmtrader.data.adapters.base import (
    CANONICAL_COLUMNS,
    AdapterCapabilities,
    AdapterResult,
)

REQUIRED_COLUMNS = ("timestamp", "open", "high", "low", "close")


class DukascopyAdapter:
    """Parse Dukascopy-style CSV with epoch-millisecond timestamps."""

    name = "dukascopy"

    def capabilities(self) -> AdapterCapabilities:
        # Bid-only (or ask-only) OHLC dumps have no volume and no measurable spread.
        return AdapterCapabilities(
            has_volume=False,
            has_spread=False,
            has_open_interest=False,
            has_depth=False,
            session_calendar="xauusd_fx",
            source="dukascopy-node",
        )

    def read(
        self,
        path: Path,
        *,
        symbol: str,
        timeframe: str,
        instrument_class: InstrumentClass,
        side: Side | None = None,
    ) -> AdapterResult:
        if not path.is_file():
            raise AdapterError(f"Dukascopy input not found: {path}")

        try:
            raw = pl.read_csv(path, infer_schema_length=10_000)
        except Exception as exc:
            raise AdapterError(f"Failed to read Dukascopy CSV {path}: {exc}") from exc

        missing = [c for c in REQUIRED_COLUMNS if c not in raw.columns]
        if missing:
            raise AdapterError(f"Dukascopy CSV missing required column(s): {', '.join(missing)}")

        # Epoch milliseconds → timezone-aware UTC. Dividing by 1000 would land in 1970 for
        # modern ms timestamps — we intentionally use ms unit.
        frame = raw.select(
            pl.col("timestamp")
            .cast(pl.Int64)
            .cast(pl.Datetime(time_unit="ms", time_zone="UTC"))
            .alias("ts"),
            pl.lit(symbol).alias("symbol"),
            pl.lit(instrument_class.value).alias("instrument_class"),
            pl.lit(timeframe).alias("timeframe"),
            pl.col("open").cast(pl.Float64),
            pl.col("high").cast(pl.Float64),
            pl.col("low").cast(pl.Float64),
            pl.col("close").cast(pl.Float64),
            pl.lit(None).cast(pl.Float64).alias("volume"),
            pl.lit(None).cast(pl.Float64).alias("open_interest"),
            (
                pl.col("close").cast(pl.Float64)
                if side == Side.BID
                else pl.lit(None).cast(pl.Float64)
            ).alias("bid"),
            (
                pl.col("close").cast(pl.Float64)
                if side == Side.ASK
                else pl.lit(None).cast(pl.Float64)
            ).alias("ask"),
        ).select(list(CANONICAL_COLUMNS))

        caps = self.capabilities()
        return AdapterResult(frame=frame, capabilities=caps, side=side)


def get_adapter(name: str) -> DukascopyAdapter:
    """Resolve an adapter by CLI name."""
    if name == "dukascopy":
        return DukascopyAdapter()
    raise AdapterError(f"Unknown adapter: {name}")
