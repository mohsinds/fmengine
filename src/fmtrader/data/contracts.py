"""Futures continuous-series construction (Panama / ratio / unadjusted).

Spot instruments use :class:`PassThroughContinuousSeriesBuilder`.
Futures use :class:`FuturesContinuousSeriesBuilder` with **causal forward
adjustment**: past bars are never revised by later rolls. Static revise-all-
history Panama is intentionally not produced for research series — it leaks.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from enum import StrEnum
from pathlib import Path
from typing import Any

import polars as pl

from fmtrader.core.enums import InstrumentClass
from fmtrader.core.errors import DataError


class AdjustmentMethod(StrEnum):
    """How to stitch successive futures contracts into a continuous series."""

    BACK_ADJUSTED = "back_adjusted"  # Panama / additive (causal forward)
    RATIO_ADJUSTED = "ratio_adjusted"
    UNADJUSTED = "unadjusted"


class RollRule(StrEnum):
    """When to roll from the front contract to the next."""

    VOLUME_CROSSOVER = "volume_crossover"
    OPEN_INTEREST_CROSSOVER = "open_interest_crossover"
    DAYS_BEFORE_EXPIRY = "days_before_expiry"


@dataclass(frozen=True)
class RollEvent:
    """A single contract roll decision."""

    roll_date: date
    from_contract: str
    to_contract: str
    metric_from: float
    metric_to: float


@dataclass
class ContinuousBuildResult:
    """Continuous series plus retained raw contracts and roll audit trail."""

    continuous: pl.DataFrame
    raw_by_contract: dict[str, pl.DataFrame]
    rolls: list[RollEvent] = field(default_factory=list)
    adjustment: AdjustmentMethod = AdjustmentMethod.BACK_ADJUSTED
    roll_rule: RollRule = RollRule.VOLUME_CROSSOVER


class ContinuousSeriesBuilder(ABC):
    """Interface for building continuous futures series from raw contracts."""

    @abstractmethod
    def build(
        self,
        raw_by_contract: dict[str, pl.DataFrame],
        *,
        adjustment: AdjustmentMethod,
        roll_rule: RollRule,
        roll_params: dict[str, Any] | None = None,
    ) -> ContinuousBuildResult:
        """Return continuous series, retained raw frames, and roll events."""


class PassThroughContinuousSeriesBuilder(ContinuousSeriesBuilder):
    """No-op builder for spot / already-continuous series (e.g. XAUUSD CFD)."""

    def build(
        self,
        raw_by_contract: dict[str, pl.DataFrame],
        *,
        adjustment: AdjustmentMethod,
        roll_rule: RollRule,
        roll_params: dict[str, Any] | None = None,
    ) -> ContinuousBuildResult:
        if len(raw_by_contract) != 1:
            raise DataError(
                "PassThroughContinuousSeriesBuilder expects exactly one series; "
                f"got {len(raw_by_contract)} — use a real roll builder for multi-contract futures"
            )
        continuous = next(iter(raw_by_contract.values()))
        return ContinuousBuildResult(
            continuous=continuous,
            raw_by_contract=dict(raw_by_contract),
            rolls=[],
            adjustment=adjustment,
            roll_rule=roll_rule,
        )


def _as_date(ts: datetime | date) -> date:
    if isinstance(ts, datetime):
        return ts.date()
    return ts


def _contract_sort_key(symbol: str) -> tuple[int, int]:
    from fmtrader.data.adapters.databento import parse_cme_symbol

    p = parse_cme_symbol(symbol)
    return (p.year, p.month)


def _daily_metric(frame: pl.DataFrame, column: str) -> dict[date, float]:
    if column not in frame.columns:
        raise DataError(f"Roll rule requires column {column!r}")
    # Sum volume / last OI per calendar day (causal: uses only that day's bars)
    g = (
        frame.select(
            pl.col("ts").dt.date().alias("d"),
            pl.col(column).cast(pl.Float64).alias("m"),
        )
        .group_by("d")
        .agg(pl.col("m").sum().alias("m"))
        .sort("d")
    )
    return {_as_date(r["d"]): float(r["m"]) for r in g.iter_rows(named=True)}


def decide_volume_rolls(
    raw_by_contract: dict[str, pl.DataFrame],
    *,
    confirm_days: int = 1,
) -> list[RollEvent]:
    """Volume-crossover rolls using only information available on/before each date.

    On each date, compare front vs next contract daily volume. Roll when the next
    contract's volume exceeds the front for ``confirm_days`` consecutive days,
    evaluated only with volumes known on those days (no look-ahead).
    """
    if confirm_days < 1:
        raise DataError("confirm_days must be >= 1")
    ordered = sorted(raw_by_contract.keys(), key=_contract_sort_key)
    if len(ordered) < 2:
        return []

    vol_maps = {c: _daily_metric(raw_by_contract[c], "volume") for c in ordered}
    all_dates = sorted({d for m in vol_maps.values() for d in m})

    rolls: list[RollEvent] = []
    front_idx = 0
    streak = 0
    for d in all_dates:
        if front_idx >= len(ordered) - 1:
            break
        front = ordered[front_idx]
        nxt = ordered[front_idx + 1]
        vf = vol_maps[front].get(d)
        vn = vol_maps[nxt].get(d)
        if vf is None or vn is None:
            streak = 0
            continue
        if vn > vf:
            streak += 1
        else:
            streak = 0
        if streak >= confirm_days:
            rolls.append(
                RollEvent(
                    roll_date=d,
                    from_contract=front,
                    to_contract=nxt,
                    metric_from=vf,
                    metric_to=vn,
                )
            )
            front_idx += 1
            streak = 0
    return rolls


def decide_oi_rolls(
    raw_by_contract: dict[str, pl.DataFrame],
    *,
    confirm_days: int = 1,
) -> list[RollEvent]:
    """Open-interest crossover — same causal structure as volume."""
    if confirm_days < 1:
        raise DataError("confirm_days must be >= 1")
    ordered = sorted(raw_by_contract.keys(), key=_contract_sort_key)
    if len(ordered) < 2:
        return []
    oi_maps = {c: _daily_metric(raw_by_contract[c], "open_interest") for c in ordered}
    all_dates = sorted({d for m in oi_maps.values() for d in m})
    rolls: list[RollEvent] = []
    front_idx = 0
    streak = 0
    for d in all_dates:
        if front_idx >= len(ordered) - 1:
            break
        front = ordered[front_idx]
        nxt = ordered[front_idx + 1]
        of_ = oi_maps[front].get(d)
        on = oi_maps[nxt].get(d)
        if of_ is None or on is None:
            streak = 0
            continue
        if on > of_:
            streak += 1
        else:
            streak = 0
        if streak >= confirm_days:
            rolls.append(
                RollEvent(
                    roll_date=d,
                    from_contract=front,
                    to_contract=nxt,
                    metric_from=of_,
                    metric_to=on,
                )
            )
            front_idx += 1
            streak = 0
    return rolls


def decide_days_before_expiry_rolls(
    raw_by_contract: dict[str, pl.DataFrame],
    *,
    days_before: int = 5,
    expiry_by_contract: dict[str, date] | None = None,
) -> list[RollEvent]:
    """Roll a fixed number of calendar days before each front contract's expiry."""
    if days_before < 0:
        raise DataError("days_before must be >= 0")
    ordered = sorted(raw_by_contract.keys(), key=_contract_sort_key)
    if len(ordered) < 2:
        return []
    expiry = dict(expiry_by_contract or {})
    for c in ordered:
        if c not in expiry:
            ts_max = raw_by_contract[c]["ts"].max()
            expiry[c] = _as_date(ts_max)  # type: ignore[arg-type]
    rolls: list[RollEvent] = []
    for i in range(len(ordered) - 1):
        front, nxt = ordered[i], ordered[i + 1]
        exp = expiry[front]
        roll_d = exp - timedelta(days=days_before)
        rolls.append(
            RollEvent(
                roll_date=roll_d,
                from_contract=front,
                to_contract=nxt,
                metric_from=float(days_before),
                metric_to=0.0,
            )
        )
    return rolls


def leaky_volume_roll_using_future(
    raw_by_contract: dict[str, pl.DataFrame],
    *,
    look_ahead_days: int = 5,
) -> list[RollEvent]:
    """Intentionally leaky roll — uses future volume. For leakage-guard tests only."""
    ordered = sorted(raw_by_contract.keys(), key=_contract_sort_key)
    if len(ordered) < 2:
        return []
    vol_maps = {c: _daily_metric(raw_by_contract[c], "volume") for c in ordered}
    all_dates = sorted({d for m in vol_maps.values() for d in m})
    rolls: list[RollEvent] = []
    front_idx = 0
    for d in all_dates:
        if front_idx >= len(ordered) - 1:
            break
        front = ordered[front_idx]
        nxt = ordered[front_idx + 1]
        future = d + timedelta(days=look_ahead_days)
        vf = vol_maps[front].get(future)
        vn = vol_maps[nxt].get(future)
        if vf is None or vn is None:
            continue
        if vn > vf:
            rolls.append(
                RollEvent(
                    roll_date=d,
                    from_contract=front,
                    to_contract=nxt,
                    metric_from=vf,
                    metric_to=vn,
                )
            )
            front_idx += 1
    return rolls


def assert_rolls_causal(
    rolls: list[RollEvent],
    raw_by_contract: dict[str, pl.DataFrame],
    *,
    metric: str = "volume",
) -> None:
    """Raise if any roll's comparison metrics are not available on the roll date.

    Planted future-info rolls (metrics taken from a later date) fail this check
    because the stored metric_from/to won't match the roll-date daily totals.
    """
    maps = {c: _daily_metric(raw_by_contract[c], metric) for c in raw_by_contract}
    for ev in rolls:
        vf = maps[ev.from_contract].get(ev.roll_date)
        vt = maps[ev.to_contract].get(ev.roll_date)
        if vf is None or vt is None:
            raise DataError(
                f"Roll on {ev.roll_date} uses {metric} not available that day "
                f"({ev.from_contract}->{ev.to_contract})"
            )
        if abs(vf - ev.metric_from) > 1e-9 or abs(vt - ev.metric_to) > 1e-9:
            raise DataError(
                f"Roll on {ev.roll_date} metrics do not match same-day {metric} "
                f"(possible look-ahead): stored ({ev.metric_from},{ev.metric_to}) "
                f"vs same-day ({vf},{vt})"
            )
        if not (ev.metric_to > ev.metric_from):
            raise DataError(
                f"Roll on {ev.roll_date} does not satisfy crossover on that day's {metric}"
            )


class FuturesContinuousSeriesBuilder(ContinuousSeriesBuilder):
    """Build a continuous futures series with causal forward adjustment."""

    def build(
        self,
        raw_by_contract: dict[str, pl.DataFrame],
        *,
        adjustment: AdjustmentMethod,
        roll_rule: RollRule,
        roll_params: dict[str, Any] | None = None,
    ) -> ContinuousBuildResult:
        if not raw_by_contract:
            raise DataError("raw_by_contract is empty")
        params = dict(roll_params or {})

        if roll_rule == RollRule.VOLUME_CROSSOVER:
            rolls = decide_volume_rolls(
                raw_by_contract, confirm_days=int(params.get("confirm_days", 1))
            )
            assert_rolls_causal(rolls, raw_by_contract, metric="volume")
        elif roll_rule == RollRule.OPEN_INTEREST_CROSSOVER:
            rolls = decide_oi_rolls(
                raw_by_contract, confirm_days=int(params.get("confirm_days", 1))
            )
            assert_rolls_causal(rolls, raw_by_contract, metric="open_interest")
        elif roll_rule == RollRule.DAYS_BEFORE_EXPIRY:
            rolls = decide_days_before_expiry_rolls(
                raw_by_contract,
                days_before=int(params.get("days_before", 5)),
                expiry_by_contract=params.get("expiry_by_contract"),
            )
        else:
            raise DataError(f"Unknown roll rule: {roll_rule}")

        continuous = _stitch_causal(raw_by_contract, rolls=rolls, adjustment=adjustment)
        # Deep-copy retention: caller must keep raw frames
        retained = {k: v.clone() for k, v in raw_by_contract.items()}
        return ContinuousBuildResult(
            continuous=continuous,
            raw_by_contract=retained,
            rolls=rolls,
            adjustment=adjustment,
            roll_rule=roll_rule,
        )


def _stitch_causal(
    raw_by_contract: dict[str, pl.DataFrame],
    *,
    rolls: list[RollEvent],
    adjustment: AdjustmentMethod,
) -> pl.DataFrame:
    """Stitch contracts chronologically; adjust only forward (no history rewrite)."""
    ordered = sorted(raw_by_contract.keys(), key=_contract_sort_key)
    roll_by_from = {r.from_contract: r for r in rolls}

    # Active contract schedule: (start_date, contract)
    schedule: list[tuple[date, str]] = [(date.min, ordered[0])]
    for r in rolls:
        schedule.append((r.roll_date, r.to_contract))

    # Collect bars per active window
    pieces: list[pl.DataFrame] = []
    add_gap = 0.0
    mul_ratio = 1.0

    for i, (start, contract) in enumerate(schedule):
        end = schedule[i + 1][0] if i + 1 < len(schedule) else date.max
        fr = raw_by_contract[contract]
        # Bars on roll date belong to the NEW contract (after roll)
        mask = (pl.col("ts").dt.date() >= start) & (pl.col("ts").dt.date() < end)
        if i == 0:
            mask = pl.col("ts").dt.date() < end
        seg = fr.filter(mask).sort("ts")
        if seg.is_empty():
            continue

        if adjustment == AdjustmentMethod.UNADJUSTED:
            adj = seg
        elif adjustment == AdjustmentMethod.BACK_ADJUSTED:
            adj = seg.with_columns(
                (pl.col("open") + add_gap).alias("open"),
                (pl.col("high") + add_gap).alias("high"),
                (pl.col("low") + add_gap).alias("low"),
                (pl.col("close") + add_gap).alias("close"),
            )
        else:  # RATIO
            adj = seg.with_columns(
                (pl.col("open") * mul_ratio).alias("open"),
                (pl.col("high") * mul_ratio).alias("high"),
                (pl.col("low") * mul_ratio).alias("low"),
                (pl.col("close") * mul_ratio).alias("close"),
            )

        # Tag active contract for audit
        adj = adj.with_columns(pl.lit(contract).alias("active_contract"))
        pieces.append(adj)

        # Update forward adjustment using gap at roll into next (if any)
        if contract in roll_by_from:
            ev = roll_by_from[contract]
            # Close of old on day before roll / last old bar; open of new on roll date
            old_fr = raw_by_contract[ev.from_contract]
            new_fr = raw_by_contract[ev.to_contract]
            old_last = old_fr.filter(pl.col("ts").dt.date() < ev.roll_date).sort("ts").tail(1)
            new_first = new_fr.filter(pl.col("ts").dt.date() >= ev.roll_date).sort("ts").head(1)
            if old_last.is_empty() or new_first.is_empty():
                # Fallback: same-day closes
                old_last = old_fr.filter(pl.col("ts").dt.date() == ev.roll_date).sort("ts").tail(1)
                new_first = new_fr.filter(pl.col("ts").dt.date() == ev.roll_date).sort("ts").head(1)
            if not old_last.is_empty() and not new_first.is_empty():
                old_c = float(old_last["close"][0])
                new_c = float(new_first["close"][0])
                if adjustment == AdjustmentMethod.BACK_ADJUSTED:
                    # Forward Panama: shift subsequent prices so new aligns to old
                    add_gap = add_gap + (old_c - new_c)
                elif adjustment == AdjustmentMethod.RATIO_ADJUSTED:
                    if new_c == 0:
                        raise DataError("Zero close on roll — cannot ratio-adjust")
                    mul_ratio = mul_ratio * (old_c / new_c)

    if not pieces:
        raise DataError("Continuous stitch produced no bars")

    out = pl.concat(pieces, how="diagonal_relaxed").sort("ts")
    # Drop duplicate timestamps preferring later schedule (shouldn't happen)
    out = out.unique(subset=["ts"], keep="last").sort("ts")
    return out


def write_raw_and_continuous(
    result: ContinuousBuildResult,
    *,
    root: Path,
    continuous_symbol: str,
    timeframe: str,
) -> dict[str, Path]:
    """Persist raw per-contract Parquet alongside continuous series under ``root``."""
    import json

    root = Path(root)
    raw_dir = root / "raw_contracts"
    raw_dir.mkdir(parents=True, exist_ok=True)
    paths: dict[str, Path] = {}
    for sym, fr in result.raw_by_contract.items():
        p = raw_dir / f"{sym}_{timeframe}.parquet"
        fr.write_parquet(p)
        paths[sym] = p
    cont_path = root / f"{continuous_symbol}_{timeframe}.parquet"
    result.continuous.write_parquet(cont_path)
    paths[continuous_symbol] = cont_path
    audit = root / "rolls.json"
    audit.write_text(
        json.dumps(
            [
                {
                    "roll_date": r.roll_date.isoformat(),
                    "from": r.from_contract,
                    "to": r.to_contract,
                    "metric_from": r.metric_from,
                    "metric_to": r.metric_to,
                }
                for r in result.rolls
            ],
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    paths["rolls"] = audit
    return paths


def builder_for(instrument_class: InstrumentClass) -> ContinuousSeriesBuilder:
    """Return the appropriate continuous-series builder for an instrument class."""
    if instrument_class in (
        InstrumentClass.SPOT_CFD,
        InstrumentClass.EQUITY,
        InstrumentClass.CRYPTO,
    ):
        return PassThroughContinuousSeriesBuilder()
    if instrument_class in (
        InstrumentClass.FUTURES_RAW,
        InstrumentClass.FUTURES_CONTINUOUS,
    ):
        return FuturesContinuousSeriesBuilder()
    raise DataError(f"No continuous-series builder for {instrument_class.value}")
