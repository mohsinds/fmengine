"""QuestDB mirror for canonical OHLCV bars (HTTP CSV import)."""

from __future__ import annotations

import tempfile
import time
from pathlib import Path

import httpx
import polars as pl

from fmtrader.config.settings import Settings, get_settings
from fmtrader.core.errors import DataError
from fmtrader.system.logging import get_logger

log = get_logger("fmtrader.data.questdb")

TABLE = "ohlcv"

_DDL = f"""
CREATE TABLE IF NOT EXISTS {TABLE} (
    ts TIMESTAMP,
    symbol SYMBOL CAPACITY 64 CACHE,
    timeframe SYMBOL CAPACITY 16 CACHE,
    instrument_class SYMBOL CAPACITY 16 CACHE,
    open DOUBLE,
    high DOUBLE,
    low DOUBLE,
    close DOUBLE,
    volume DOUBLE,
    open_interest DOUBLE,
    bid DOUBLE,
    ask DOUBLE,
    is_tradable BOOLEAN
) TIMESTAMP(ts) PARTITION BY MONTH WAL
DEDUP UPSERT KEYS(ts, symbol, timeframe);
"""


def ensure_ohlcv_table(settings: Settings | None = None) -> None:
    """Create the OHLCV table if it does not exist."""
    cfg = settings or get_settings()
    _exec(_DDL, cfg)


def _exec(query: str, settings: Settings) -> dict[str, object]:
    url = f"{settings.questdb_http_url.rstrip('/')}/exec"
    with httpx.Client(timeout=120.0) as client:
        resp = client.get(url, params={"query": query})
        if resp.status_code >= 400:
            raise DataError(f"QuestDB exec failed: {resp.status_code} {resp.text}")
        return resp.json()  # type: ignore[no-any-return]


def truncate_symbol(
    *,
    symbol: str,
    timeframe: str,
    settings: Settings | None = None,
) -> None:
    """Drop and recreate the OHLCV table for a clean idempotent re-ingest.

    QuestDB 8.2 does not support ``DELETE FROM``; with a single research series
    in Phase 2, dropping the table is the reliable reset.
    """
    del symbol, timeframe  # single-table Phase 2 mirror
    cfg = settings or get_settings()
    try:
        _exec(f"DROP TABLE IF EXISTS {TABLE};", cfg)
    except DataError as exc:
        log.info("questdb_drop_skipped", detail=str(exc)[:200])
    ensure_ohlcv_table(cfg)


def mirror_frame(
    frame: pl.DataFrame,
    *,
    settings: Settings | None = None,
) -> int:
    """Upsert bars into QuestDB via CSV ``/imp``. Returns row count written."""
    cfg = settings or get_settings()
    ensure_ohlcv_table(cfg)

    export = frame.select(
        [
            "ts",
            "symbol",
            "timeframe",
            "instrument_class",
            "open",
            "high",
            "low",
            "close",
            "volume",
            "open_interest",
            "bid",
            "ask",
            "is_tradable",
        ]
    ).with_columns(
        pl.col("ts").dt.strftime("%Y-%m-%dT%H:%M:%S.%3fZ").alias("ts"),
    )

    with tempfile.NamedTemporaryFile(suffix=".csv", delete=False, mode="w") as tmp:
        tmp_path = Path(tmp.name)
    try:
        export.write_csv(tmp_path)
        url = f"{cfg.questdb_http_url.rstrip('/')}/imp"
        with tmp_path.open("rb") as fh, httpx.Client(timeout=600.0) as client:
            resp = client.post(
                url,
                params={
                    "name": TABLE,
                    "timestamp": "ts",
                    "partitionBy": "MONTH",
                    "overwrite": "false",
                    "fmt": "csv",
                },
                files={"data": ("bars.csv", fh, "text/csv")},
            )
        if resp.status_code >= 400:
            raise DataError(f"QuestDB /imp failed: {resp.status_code} {resp.text}")
        log.info("questdb_mirror_complete", rows=frame.height, detail=resp.text[:300])
    finally:
        tmp_path.unlink(missing_ok=True)

    # WAL visibility: brief retry on count
    for _ in range(10):
        n = count_rows(
            symbol=str(frame["symbol"][0]), timeframe=str(frame["timeframe"][0]), settings=cfg
        )
        if n >= frame.height:
            break
        time.sleep(0.2)
    return frame.height


def count_rows(
    *,
    symbol: str,
    timeframe: str,
    settings: Settings | None = None,
) -> int:
    """Return QuestDB row count for symbol/timeframe."""
    cfg = settings or get_settings()
    ensure_ohlcv_table(cfg)
    payload = _exec(
        f"SELECT count() FROM {TABLE} WHERE symbol='{symbol}' AND timeframe='{timeframe}'",
        cfg,
    )
    dataset = payload.get("dataset")
    if not isinstance(dataset, list) or not dataset:
        return 0
    row = dataset[0]
    if not isinstance(row, list) or not row:
        return 0
    return int(row[0])
