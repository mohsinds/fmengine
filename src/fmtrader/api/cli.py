"""``fmtrader api`` CLI — serve the FastAPI review contract."""

from __future__ import annotations

import typer

api_app = typer.Typer(help="FastAPI review / observability server.")


@api_app.command("serve")
def serve(
    host: str = typer.Option("127.0.0.1", "--host"),
    port: int = typer.Option(8000, "--port"),
    reload: bool = typer.Option(False, "--reload"),
) -> None:
    """Run uvicorn against ``fmtrader.api.app:app``."""
    import uvicorn

    uvicorn.run(
        "fmtrader.api.app:app",
        host=host,
        port=port,
        reload=reload,
    )
