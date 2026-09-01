"""Settings fail-fast behaviour."""

from __future__ import annotations

import pytest

from fmtrader.config.settings import Settings
from fmtrader.core.errors import SettingsError


def test_missing_required_env_var_fails_fast_with_named_error() -> None:
    settings = Settings(
        questdb_user="",
        questdb_password="",
        postgres_user="",
        postgres_password="",
    )
    with pytest.raises(SettingsError) as excinfo:
        settings.require_infra_credentials()
    msg = str(excinfo.value)
    assert "QUESTDB_USER" in msg
    assert "QUESTDB_PASSWORD" in msg
    assert "POSTGRES_USER" in msg
    assert "POSTGRES_PASSWORD" in msg


def test_postgres_dsn_requires_credentials() -> None:
    settings = Settings(
        questdb_user="q",
        questdb_password="qp",
        postgres_user="",
        postgres_password="pp",
    )
    with pytest.raises(SettingsError) as excinfo:
        _ = settings.postgres_dsn
    assert "POSTGRES_USER" in str(excinfo.value)
