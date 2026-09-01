"""Data layer: adapters, quality, catalog, ingest."""

from fmtrader.data.ingest import IngestResult, ingest, load_manifest

__all__ = ["IngestResult", "ingest", "load_manifest"]
