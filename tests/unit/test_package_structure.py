"""Enforce the dependency-free invariant on ``fmtrader.core``."""

from __future__ import annotations

import ast
from pathlib import Path

import fmtrader.core


def _core_root() -> Path:
    return Path(fmtrader.core.__file__).resolve().parent


def _iter_python_files(root: Path) -> list[Path]:
    return sorted(p for p in root.rglob("*.py") if p.is_file())


def _imported_modules(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                names.append(alias.name)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.append(node.module)
    return names


def test_core_has_zero_external_fmtrader_imports() -> None:
    """``core`` may import ``fmtrader.core.*`` only — never config/data/etc."""
    forbidden: list[str] = []
    for path in _iter_python_files(_core_root()):
        for mod in _imported_modules(path):
            if not mod.startswith("fmtrader"):
                continue
            if mod == "fmtrader.core" or mod.startswith("fmtrader.core."):
                continue
            forbidden.append(f"{path.name}: {mod}")
    assert forbidden == [], f"core leaked imports: {forbidden}"
