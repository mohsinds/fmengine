"""Dataset snapshot endpoints."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from fmtrader.api.deps import get_paths
from fmtrader.core.errors import DataError
from fmtrader.data.catalog import SnapshotManifest
from fmtrader.data.ingest import load_manifest

router = APIRouter(tags=["datasets"])


def _list_snapshot_ids() -> list[str]:
    root = get_paths().snapshots
    root.mkdir(parents=True, exist_ok=True)
    return sorted(p.stem for p in root.glob("*.json"))


def _load(dataset_id: str) -> SnapshotManifest:
    try:
        return load_manifest(get_paths().snapshots, dataset_id)
    except DataError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/datasets")
def list_datasets() -> dict[str, Any]:
    items: list[dict[str, Any]] = []
    for did in _list_snapshot_ids():
        try:
            snap = _load(did)
        except HTTPException:
            continue
        items.append(
            {
                "id": snap.dataset_id,
                "symbol": snap.symbol,
                "timeframe": snap.timeframe,
                "rows": snap.rows,
                "start": snap.start,
                "end": snap.end,
                "has_volume": snap.has_volume,
                "content_hash": snap.content_hash,
            }
        )
    return {"items": items, "count": len(items)}


@router.get("/datasets/{dataset_id}")
def get_dataset(dataset_id: str) -> dict[str, Any]:
    return _load(dataset_id).to_dict()


@router.get("/datasets/{dataset_id}/quality")
def dataset_quality(dataset_id: str) -> dict[str, Any]:
    snap = _load(dataset_id)
    return {"dataset_id": dataset_id, "quality_report": snap.quality_report}


@router.get("/datasets/{dataset_id}/bars")
def dataset_bars(
    dataset_id: str,
    from_: str | None = Query(default=None, alias="from"),
    to: str | None = None,
    timeframe: str | None = None,
) -> dict[str, Any]:
    _load(dataset_id)
    return {
        "dataset_id": dataset_id,
        "from": from_,
        "to": to,
        "timeframe": timeframe,
        "bars": [],
        "status": "stub",
    }


class IngestBody(BaseModel):
    source: str = "dukascopy"
    symbol: str = "XAUUSD"
    path: str | None = None
    options: dict[str, Any] = Field(default_factory=dict)


@router.post("/datasets/ingest")
def datasets_ingest(body: IngestBody) -> dict[str, Any]:
    return {
        "status": "stub",
        "message": "Ingest not wired; use fmtrader data ingest CLI",
        "request": body.model_dump(),
    }
