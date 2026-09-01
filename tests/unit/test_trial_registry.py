"""Trial registry unit tests."""

from __future__ import annotations

from pathlib import Path

from fmtrader.backtest.validation.registry import TrialRecord, TrialRegistry, config_hash


def test_every_evaluated_config_is_written(tmp_path: Path) -> None:
    reg = TrialRegistry(tmp_path / "t.sqlite")
    for i in range(5):
        params = {"fast": i, "slow": 20}
        reg.record(
            TrialRecord(
                strategy="ema_cross",
                params=params,
                config_hash=config_hash("ema_cross", params),
                metrics={"sharpe": 0.1 * i},
                source="manual",
                dataset_id="ds",
                lane="vectorbt",
            )
        )
    assert reg.count(strategy="ema_cross") == 5


def test_duplicate_config_detected_by_hash(tmp_path: Path) -> None:
    reg = TrialRegistry(tmp_path / "t.sqlite")
    params = {"fast": 12, "slow": 26}
    h = config_hash("ema_cross", params)
    assert not reg.has_config(h)
    reg.record(
        TrialRecord(
            strategy="ema_cross",
            params=params,
            config_hash=h,
            metrics={},
            source="sweep",
            dataset_id="ds",
            lane="vectorbt",
        )
    )
    assert reg.has_config(h)


def test_trial_count_per_strategy_accurate(tmp_path: Path) -> None:
    reg = TrialRegistry(tmp_path / "t.sqlite")
    for src, strat in [("manual", "a"), ("agent", "a"), ("sweep", "b")]:
        reg.record(
            TrialRecord(
                strategy=strat,
                params={"x": 1},
                config_hash=config_hash(strat, {"x": 1, "src": src}),
                metrics={},
                source=src,  # type: ignore[arg-type]
                dataset_id="ds",
                lane="vectorbt",
            )
        )
    assert reg.count(strategy="a") == 2
    assert reg.count(strategy="b") == 1


def test_manual_and_agent_runs_share_the_registry(tmp_path: Path) -> None:
    reg = TrialRegistry(tmp_path / "t.sqlite")
    for source in ("manual", "agent"):
        reg.record(
            TrialRecord(
                strategy="ema_cross",
                params={"fast": 5, "source": source},
                config_hash=config_hash("ema_cross", {"fast": 5, "source": source}),
                metrics={"sharpe": 1.0},
                source=source,  # type: ignore[arg-type]
                dataset_id="ds",
                lane="vectorbt",
            )
        )
    sources = {t.source for t in reg.list_trials(strategy="ema_cross")}
    assert sources == {"manual", "agent"}
