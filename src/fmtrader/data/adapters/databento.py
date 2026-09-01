"""CME futures symbol parsing and Databento OHLCV adapter.

Capability audit (GC/MGC OHLCV path):
- Real traded volume: yes (exchange volume)
- Price: last-trade OHLC (not bid-only)
- Open interest: yes when present in vendor file
- Order book depth: no on this OHLCV path (has_depth=false)
- Session: COMEX metals (comex_metals calendar)
- Timestamp: exchange time, UTC, bar-open
- Revisions: bars treated as final once published
- Rolls: handled by ContinuousSeriesBuilder — not in this adapter
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import polars as pl

from fmtrader.core.enums import InstrumentClass, Side
from fmtrader.core.errors import AdapterError
from fmtrader.data.adapters.base import (
    CANONICAL_COLUMNS,
    AdapterCapabilities,
    AdapterResult,
)

# Root + month code + 1-4 digit year: GCZ5, GCZ25, GCG2026, MGCZ2025
_CONTRACT_RE = re.compile(r"^(?P<root>[A-Z]{1,3})(?P<month>[FGHJKMNQUVXZ])(?P<year>\d{1,4})$")

_MONTH_CODES = {
    "F": 1,
    "G": 2,
    "H": 3,
    "J": 4,
    "K": 5,
    "M": 6,
    "N": 7,
    "Q": 8,
    "U": 9,
    "V": 10,
    "X": 11,
    "Z": 12,
}


@dataclass(frozen=True)
class ParsedContract:
    root: str
    month_code: str
    month: int
    year: int
    symbol: str


def parse_cme_symbol(symbol: str) -> ParsedContract:
    """Parse a CME futures symbol into root / month / year."""
    s = symbol.strip().upper().replace(".", "").replace("-", "")
    m = _CONTRACT_RE.match(s)
    if not m:
        raise AdapterError(
            f"Unrecognized CME contract symbol {symbol!r}; expected e.g. GCZ5, GCG26, MGCZ2025"
        )
    root = m.group("root")
    month_code = m.group("month")
    year_raw = m.group("year")
    if len(year_raw) == 1:
        # CME short year: digit within the current decade (research horizon 2020s)
        year = 2020 + int(year_raw)
    elif len(year_raw) == 2:
        y = int(year_raw)
        year = 2000 + y if y < 80 else 1900 + y
    else:
        year = int(year_raw)
    return ParsedContract(
        root=root,
        month_code=month_code,
        month=_MONTH_CODES[month_code],
        year=year,
        symbol=f"{root}{month_code}{year_raw}",
    )


class DatabentoAdapter:
    """Read Databento-style OHLCV (+ optional OI) CSV/Parquet into canonical bars.

    Does not require the ``databento`` Python package for file-based ingest.
    Live API fetch is optional behind ``DATABENTO_API_KEY`` (Phase 9+ ops).
    """

    name = "databento"

    def capabilities(self) -> AdapterCapabilities:
        return AdapterCapabilities(
            has_volume=True,
            has_spread=False,  # OHLCV last; spread needs MBP
            has_open_interest=True,
            has_depth=False,
            session_calendar="comex_metals",
            source="databento",
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
            raise AdapterError(f"Databento input not found: {path}")

        # Validate symbol shape for futures
        if instrument_class in (
            InstrumentClass.FUTURES_RAW,
            InstrumentClass.FUTURES_CONTINUOUS,
        ):
            parse_cme_symbol(symbol)

        try:
            if path.suffix.lower() in {".parquet", ".pq"}:
                raw = pl.read_parquet(path)
            else:
                raw = pl.read_csv(path, infer_schema_length=10_000)
        except Exception as exc:
            raise AdapterError(f"Failed to read Databento file {path}: {exc}") from exc

        cols = {c.lower(): c for c in raw.columns}

        # Accept common aliases
        def _col(*names: str) -> str | None:
            for n in names:
                if n in cols:
                    return cols[n]
            return None

        ts_col = _col("ts", "timestamp", "ts_event", "datetime")
        o_col = _col("open")
        h_col = _col("high")
        l_col = _col("low")
        c_col = _col("close")
        v_col = _col("volume", "vol")
        oi_col = _col("open_interest", "oi", "openinterest")
        if ts_col is None or o_col is None or h_col is None or l_col is None or c_col is None:
            raise AdapterError("Databento file must include ts/timestamp, open, high, low, close")
        if v_col is None:
            raise AdapterError("Databento futures OHLCV requires a volume column")

        ts_name: str = ts_col
        ts_series = raw[ts_name]
        ts_expr: pl.Expr = pl.col(ts_name)
        # Handle epoch ms/us or datetime strings
        if ts_series.dtype in (pl.Int64, pl.UInt64, pl.Int32):
            sample = int(ts_series.drop_nulls().head(1)[0]) if raw.height else 0
            unit: Literal["us", "ms"] = "us" if sample > 10_000_000_000_000 else "ms"
            ts_expr = ts_expr.cast(pl.Datetime(time_unit=unit, time_zone="UTC"))
        else:
            ts_expr = ts_expr.cast(pl.Datetime(time_unit="ms", time_zone="UTC"))

        frame = raw.select(
            ts_expr.alias("ts"),
            pl.lit(symbol).alias("symbol"),
            pl.lit(instrument_class.value).alias("instrument_class"),
            pl.lit(timeframe).alias("timeframe"),
            pl.col(o_col).cast(pl.Float64).alias("open"),
            pl.col(h_col).cast(pl.Float64).alias("high"),
            pl.col(l_col).cast(pl.Float64).alias("low"),
            pl.col(c_col).cast(pl.Float64).alias("close"),
            pl.col(v_col).cast(pl.Float64).alias("volume"),
            (pl.col(oi_col).cast(pl.Float64) if oi_col else pl.lit(None).cast(pl.Float64)).alias(
                "open_interest"
            ),
            pl.lit(None).cast(pl.Float64).alias("bid"),
            pl.lit(None).cast(pl.Float64).alias("ask"),
        ).select(list(CANONICAL_COLUMNS))

        return AdapterResult(frame=frame, capabilities=self.capabilities(), side=side)
