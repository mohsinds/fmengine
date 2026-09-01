"""ExecutionRecorder tests."""

from __future__ import annotations

from pathlib import Path

from fmtrader.execution.recorder import ExecutionManifest, ExecutionRecorder, new_execution_id


def _man(**kwargs: object) -> ExecutionManifest:
    base = dict(
        execution_id=new_execution_id(),
        strategy="buy_and_hold",
        params={},
        dataset_id="ds",
        content_hash="sha256:abc",
        lane="vectorbt",
        cost_multiplier=1.0,
        seed=0,
        git_sha=None,
        started_at="2026-01-01T00:00:00+00:00",
    )
    base.update(kwargs)
    return ExecutionManifest(**base)  # type: ignore[arg-type]


def test_manifest_captures_all_required_sections(tmp_path: Path) -> None:
    man = _man()
    with ExecutionRecorder(tmp_path, man) as rec:
        rec.step("simulate", {"ok": True})
        man.metrics_net = {"sharpe": 1.0}
        man.metrics_gross = {"sharpe": 1.2}
        man.cost_drag_pct = 10.0
        man.funnel = {"counts": {}, "drops": {}}
        path = rec.complete()
    assert path.exists()
    text = path.read_text()
    assert "metrics_net" in text and "funnel" in text and "cost_drag_pct" in text


def test_incomplete_manifest_marked_and_excluded_from_promotion(tmp_path: Path) -> None:
    man = _man()
    with ExecutionRecorder(tmp_path, man) as rec:
        rec.step("halfway")
        # exit without complete()
    loaded = ExecutionManifest(
        **__import__("json").loads((tmp_path / f"{man.execution_id}.partial.json").read_text())
    )
    assert loaded.status in {"incomplete", "running", "failed"}
    assert loaded.promotable is False


def test_crash_writes_partial_record_with_failure_point(tmp_path: Path) -> None:
    man = _man()
    try:
        with ExecutionRecorder(tmp_path, man) as rec:
            rec.step("before_boom")
            raise RuntimeError("boom")
    except RuntimeError:
        pass
    partial = tmp_path / f"{man.execution_id}.partial.json"
    assert partial.exists()
    data = __import__("json").loads(partial.read_text())
    assert data["status"] == "failed"
    assert data["failure_point"] == "before_boom"


def test_record_is_append_only(tmp_path: Path) -> None:
    man = _man()
    with ExecutionRecorder(tmp_path, man) as rec:
        rec.step("a")
        rec.step("b")
        rec.complete()
    assert [s["name"] for s in man.steps][:3] == ["start", "a", "b"]
