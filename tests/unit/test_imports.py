"""Smoke-import key packages."""

from __future__ import annotations


def test_import_fmtrader() -> None:
    import fmtrader

    assert fmtrader.__version__


def test_import_core_and_config() -> None:
    from fmtrader import config, core
    from fmtrader.core import InstrumentClass, Side

    assert InstrumentClass.SPOT_CFD.value == "spot_cfd"
    assert Side.BID.value == "bid"
    assert config.get_settings is not None
    assert core.FmtraderError is not None


def test_import_system() -> None:
    from fmtrader.system import collect_memory_snapshot, configure_logging, run_all_health_checks

    assert callable(configure_logging)
    assert callable(collect_memory_snapshot)
    assert callable(run_all_health_checks)


def test_import_cli() -> None:
    from fmtrader.cli import app, main

    assert callable(main)
    assert app is not None
