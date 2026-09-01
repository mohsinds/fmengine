"""Versioned Parquet feature store keyed by dataset + feature-set version."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import polars as pl

from fmtrader.core.errors import FeatureError


@dataclass(frozen=True)
class FeatureSetManifest:
    """Immutable identity for a materialised feature matrix."""

    dataset_id: str
    feature_set_name: str
    feature_set_version: str
    definition_hash: str
    rows: int
    columns: list[str]
    created_at: str
    peak_memory_gb: float | None
    elapsed_sec: float | None
    path: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "dataset_id": self.dataset_id,
            "feature_set_name": self.feature_set_name,
            "feature_set_version": self.feature_set_version,
            "definition_hash": self.definition_hash,
            "rows": self.rows,
            "columns": self.columns,
            "created_at": self.created_at,
            "peak_memory_gb": self.peak_memory_gb,
            "elapsed_sec": self.elapsed_sec,
            "path": self.path,
        }

    def write(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(self.to_dict(), indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )

    @classmethod
    def load(cls, path: Path) -> FeatureSetManifest:
        return cls(**json.loads(path.read_text(encoding="utf-8")))


def definition_hash(payload: dict[str, Any]) -> str:
    """Stable SHA-256 over canonical JSON of a feature-set definition."""
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return f"sha256:{hashlib.sha256(blob).hexdigest()}"


class FeatureStore:
    """Read/write feature matrices under ``data/features``."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    def path_for(self, *, dataset_id: str, feature_set_version: str) -> Path:
        return self.root / dataset_id / feature_set_version

    def write(
        self,
        frame: pl.DataFrame,
        *,
        dataset_id: str,
        feature_set_name: str,
        feature_set_version: str,
        def_hash: str,
        created_at: str,
        peak_memory_gb: float | None = None,
        elapsed_sec: float | None = None,
    ) -> FeatureSetManifest:
        if frame.is_empty():
            raise FeatureError("Refusing to write empty feature frame")
        if "ts" not in frame.columns:
            raise FeatureError("Feature frame must include ts")

        out_dir = self.path_for(dataset_id=dataset_id, feature_set_version=feature_set_version)
        if out_dir.exists():
            import shutil

            shutil.rmtree(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        parquet_path = out_dir / "features.parquet"
        # float32 where possible to stay inside memory budget
        casted = frame
        for col, dtype in zip(frame.columns, frame.dtypes, strict=True):
            if dtype == pl.Float64:
                casted = casted.with_columns(pl.col(col).cast(pl.Float32))
        casted.sort("ts").write_parquet(parquet_path, compression="zstd")

        manifest = FeatureSetManifest(
            dataset_id=dataset_id,
            feature_set_name=feature_set_name,
            feature_set_version=feature_set_version,
            definition_hash=def_hash,
            rows=casted.height,
            columns=list(casted.columns),
            created_at=created_at,
            peak_memory_gb=peak_memory_gb,
            elapsed_sec=elapsed_sec,
            path=str(parquet_path),
        )
        manifest.write(out_dir / "manifest.json")
        return manifest

    def read(self, *, dataset_id: str, feature_set_version: str) -> pl.DataFrame:
        path = self.path_for(dataset_id=dataset_id, feature_set_version=feature_set_version)
        pq = path / "features.parquet"
        if not pq.exists():
            raise FeatureError(f"Feature set not found: {path}")
        return pl.read_parquet(pq).sort("ts")

    def list_versions(self, *, dataset_id: str) -> list[FeatureSetManifest]:
        base = self.root / dataset_id
        if not base.exists():
            return []
        out: list[FeatureSetManifest] = []
        for child in sorted(base.iterdir()):
            man = child / "manifest.json"
            if man.exists():
                out.append(FeatureSetManifest.load(man))
        return out
