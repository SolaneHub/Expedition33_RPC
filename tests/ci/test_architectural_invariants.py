"""CI test validating architectural invariants and temporal decoupling across the codebase."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

SRC_DIR = Path(__file__).resolve().parents[2] / "src" / "expedition33_rpc"


def _is_time_monotonic(node: ast.AST) -> bool:
    """Check if AST node represents time.monotonic / monotonic call or reference."""
    if isinstance(node, ast.Attribute) and node.attr == "monotonic":
        return True
    return isinstance(node, ast.Name) and node.id == "monotonic"


def _is_time_time(node: ast.AST) -> bool:
    """Check if AST node represents time.time / time call or reference."""
    if isinstance(node, ast.Attribute) and node.attr == "time":
        return True
    return isinstance(node, ast.Name) and node.id == "time"


def test_all_src_files_ast_parseable() -> None:
    """Verifies that every python file in src/expedition33_rpc can be parsed via ast.parse."""
    py_files = list(SRC_DIR.rglob("*.py"))
    assert py_files, "No python files found in src/expedition33_rpc"
    for py_file in py_files:
        content = py_file.read_text(encoding="utf-8")
        tree = ast.parse(content, filename=str(py_file))
        assert isinstance(tree, ast.Module)


def test_discord_rpc_no_monotonic_on_wire_timestamps() -> None:
    """Verifies that time.monotonic is never assigned/serialized to outbound Discord timestamps."""
    rpc_file = SRC_DIR / "integrations" / "discord_rpc.py"
    assert rpc_file.exists()
    content = rpc_file.read_text(encoding="utf-8")
    tree = ast.parse(content, filename=str(rpc_file))

    # Check that in discord_rpc.py, no assignment or keyword arg to start_timestamp uses monotonic
    for node in ast.walk(tree):
        # Check keyword arguments in function calls (e.g. set_activity(..., start_timestamp=...))
        if isinstance(node, ast.Call):
            for kw in node.keywords:
                if kw.arg in ("start_timestamp", "timestamps", "start"):
                    for child in ast.walk(kw.value):
                        assert not _is_time_monotonic(child), (
                            f"Forbidden monotonic assigned to {kw.arg} in {rpc_file}:{node.lineno}"
                        )

        # Check variable assignment (start_timestamp = ...)
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id in ("start_timestamp", "start"):
                    for child in ast.walk(node.value):
                        assert not _is_time_monotonic(child), (
                            f"Forbidden monotonic assigned to {target.id} in {rpc_file}:{node.lineno}"
                        )


def test_presentation_no_monotonic_on_wire_timestamps() -> None:
    """Verifies that time.monotonic is never assigned/serialized to outbound Discord timestamps in presentation.py."""
    presentation_file = SRC_DIR / "ui" / "presentation.py"
    assert presentation_file.exists()
    content = presentation_file.read_text(encoding="utf-8")
    tree = ast.parse(content, filename=str(presentation_file))

    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            for kw in node.keywords:
                if kw.arg in ("start_timestamp", "timestamps", "start"):
                    for child in ast.walk(kw.value):
                        assert not _is_time_monotonic(child), (
                            f"Forbidden monotonic assigned to {kw.arg} in {presentation_file}:{node.lineno}"
                        )

        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id in ("start_timestamp", "start"):
                    for child in ast.walk(node.value):
                        assert not _is_time_monotonic(child), (
                            f"Forbidden monotonic assigned to {target.id} in {presentation_file}:{node.lineno}"
                        )


def test_orchestrator_wait_and_deadline_no_time_time() -> None:
    """Verifies that in orchestrator.py, _stop_event.wait and deadline calculations never invoke time.time()."""
    orchestrator_file = SRC_DIR / "core" / "orchestrator.py"
    assert orchestrator_file.exists()
    content = orchestrator_file.read_text(encoding="utf-8")
    tree = ast.parse(content, filename=str(orchestrator_file))

    for node in ast.walk(tree):
        # 1. Check _stop_event.wait calls
        if isinstance(node, ast.Call):
            func = node.func
            if (
                isinstance(func, ast.Attribute)
                and func.attr == "wait"
                and isinstance(func.value, ast.Attribute)
                and func.value.attr == "_stop_event"
            ):
                for child in ast.walk(node):
                    if isinstance(child, ast.Call) and _is_time_time(child.func):
                        pytest.fail(
                            f"time.time() invoked in _stop_event.wait call at line {node.lineno}"
                        )

        # 2. Check assignments to variables containing 'deadline'
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and "deadline" in target.id.lower():
                    for child in ast.walk(node.value):
                        if isinstance(child, ast.Call) and _is_time_time(child.func):
                            pytest.fail(
                                f"time.time() invoked in deadline calculation at line {node.lineno}"
                            )
