"""Gate evaluator unit tests."""

from __future__ import annotations

from fmtrader.backtest.validation.gates import evaluate_gates


def test_noise_verdict_when_dsr_negative() -> None:
    g = evaluate_gates(
        dsr=0.1,
        pbo=0.9,
        net_sharpe_1x=1.5,
        net_sharpe_15x=1.0,
        cost_drag_pct=10.0,
        trade_count=100,
        holdout_consumed=False,
    )
    assert g.verdict == "NOISE"


def test_fragile_verdict_when_edge_dies_at_1_5x_costs() -> None:
    g = evaluate_gates(
        dsr=0.8,
        pbo=0.2,
        net_sharpe_1x=1.2,
        net_sharpe_15x=-0.1,
        cost_drag_pct=40.0,
        trade_count=100,
        holdout_consumed=False,
    )
    assert g.verdict == "FRAGILE"


def test_candidate_requires_all_gates_passed() -> None:
    g = evaluate_gates(
        dsr=0.8,
        pbo=0.2,
        net_sharpe_1x=1.0,
        net_sharpe_15x=0.5,
        cost_drag_pct=20.0,
        trade_count=100,
        holdout_consumed=False,
        regime_ok=True,
    )
    assert g.verdict == "CANDIDATE"


def test_validated_requires_holdout_consumed() -> None:
    g = evaluate_gates(
        dsr=0.8,
        pbo=0.2,
        net_sharpe_1x=1.0,
        net_sharpe_15x=0.5,
        cost_drag_pct=20.0,
        trade_count=100,
        holdout_consumed=True,
        holdout_passed=True,
        regime_ok=True,
    )
    assert g.verdict == "VALIDATED"
