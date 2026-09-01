"""FastAPI application factory — UI is a client of this contract."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from fmtrader.api.routers import (
    campaigns,
    datasets,
    executions,
    features,
    registry,
    runs,
    strategies,
    sweeps,
    system,
    vault,
)


def create_app() -> FastAPI:
    app = FastAPI(
        title="fmtrader API",
        version="0.1.0",
        description="Frozen review/observability contract for fmtrader-web.",
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    api_prefix = "/api"
    routers = (
        campaigns,
        runs,
        executions,
        strategies,
        sweeps,
        registry,
        datasets,
        features,
        vault,
        system,
    )
    for mod in routers:
        app.include_router(mod.router, prefix=api_prefix)
    return app


app = create_app()
