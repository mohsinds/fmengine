"""AST audit helpers that catch common look-ahead patterns in feature code."""

from __future__ import annotations

import ast
from pathlib import Path

from fmtrader.core.errors import FeatureError


def scan_source_for_leakage(source: str, *, path: str = "<string>") -> list[str]:
    """Return human-readable findings for look-ahead smells in ``source``."""
    tree = ast.parse(source, filename=path)
    findings: list[str] = []

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        for kw in node.keywords:
            if kw.arg == "center" and isinstance(kw.value, ast.Constant) and kw.value.value is True:
                findings.append(f"{path}:{node.lineno}: center=True in call")
        func = node.func
        if isinstance(func, ast.Attribute) and func.attr == "shift" and node.args:
            arg0 = node.args[0]
            if (
                isinstance(arg0, ast.UnaryOp)
                and isinstance(arg0.op, ast.USub)
                and isinstance(arg0.operand, ast.Constant)
                and isinstance(arg0.operand.value, int | float)
                and arg0.operand.value > 0
            ):
                findings.append(f"{path}:{node.lineno}: shift(-N) look-ahead")
            elif (
                isinstance(arg0, ast.Constant)
                and isinstance(arg0.value, int | float)
                and arg0.value < 0
            ):
                findings.append(f"{path}:{node.lineno}: shift(negative) look-ahead")
    return findings


def audit_paths(paths: list[Path]) -> None:
    """Raise ``FeatureError`` if any path contains planted look-ahead smells."""
    all_findings: list[str] = []
    for path in paths:
        text = path.read_text(encoding="utf-8")
        all_findings.extend(scan_source_for_leakage(text, path=str(path)))
    if all_findings:
        raise FeatureError("Leakage audit failed:\n" + "\n".join(all_findings))
