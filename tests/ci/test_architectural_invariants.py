"""CI test validating architectural invariants and temporal decoupling across the codebase."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

SRC_DIR = Path(__file__).resolve().parents[2] / "src" / "expedition33_rpc"

_FORBIDDEN_TIMESTAMP_TARGETS = frozenset({"start_timestamp", "timestamps", "start", "start_time"})
_LOW_LEVEL_OS_MODULES = frozenset({"ctypes", "winreg", "fcntl", "msvcrt"})


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
                if kw.arg in _FORBIDDEN_TIMESTAMP_TARGETS:
                    for child in ast.walk(kw.value):
                        assert not _is_time_monotonic(child), (
                            f"Forbidden monotonic assigned to {kw.arg} in {rpc_file}:{node.lineno}"
                        )

        # Check variable assignment (start_timestamp = ...)
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id in _FORBIDDEN_TIMESTAMP_TARGETS:
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
                if kw.arg in _FORBIDDEN_TIMESTAMP_TARGETS:
                    for child in ast.walk(kw.value):
                        assert not _is_time_monotonic(child), (
                            f"Forbidden monotonic assigned to {kw.arg} in {presentation_file}:{node.lineno}"
                        )

        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id in _FORBIDDEN_TIMESTAMP_TARGETS:
                    for child in ast.walk(node.value):
                        assert not _is_time_monotonic(child), (
                            f"Forbidden monotonic assigned to {target.id} in {presentation_file}:{node.lineno}"
                        )


def test_detector_and_timer_tracker_no_monotonic_on_start_timestamps() -> None:
    """Verifies that in detector.py and timer_tracker.py time.monotonic is never assigned or passed

    to parameters/attributes named 'start_timestamp', 'timestamps', 'start', or saved as 'start_time'.
    """
    detection_files = [
        SRC_DIR / "detection" / "detector.py",
        SRC_DIR / "detection" / "timer_tracker.py",
    ]

    for py_file in detection_files:
        assert py_file.exists(), f"File missing: {py_file}"
        content = py_file.read_text(encoding="utf-8")
        tree = ast.parse(content, filename=str(py_file))

        for node in ast.walk(tree):
            # 1. Keyword arguments in function/method calls
            if isinstance(node, ast.Call):
                for kw in node.keywords:
                    if kw.arg in _FORBIDDEN_TIMESTAMP_TARGETS:
                        for child in ast.walk(kw.value):
                            assert not _is_time_monotonic(child), (
                                f"Forbidden monotonic passed to parameter '{kw.arg}' "
                                f"in {py_file.name}:{node.lineno}"
                            )

            # 2. Variable or attribute assignments (targets = ...)
            if isinstance(node, ast.Assign):
                target_names: set[str] = set()
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        target_names.add(target.id)
                    elif isinstance(target, ast.Attribute):
                        target_names.add(target.attr)
                matched = target_names & _FORBIDDEN_TIMESTAMP_TARGETS
                if matched:
                    for child in ast.walk(node.value):
                        assert not _is_time_monotonic(child), (
                            f"Forbidden monotonic assigned to {matched} in {py_file.name}:{node.lineno}"
                        )

            # 3. AnnAssign (e.g. start_time: float = ...)
            if isinstance(node, ast.AnnAssign) and node.value is not None:
                target_name = None
                if isinstance(node.target, ast.Name):
                    target_name = node.target.id
                elif isinstance(node.target, ast.Attribute):
                    target_name = node.target.attr
                if target_name in _FORBIDDEN_TIMESTAMP_TARGETS:
                    for child in ast.walk(node.value):
                        assert not _is_time_monotonic(child), (
                            f"Forbidden monotonic assigned to '{target_name}' in {py_file.name}:{node.lineno}"
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


def test_no_low_level_os_module_leakage_outside_platform() -> None:
    """Verifies that low-level OS modules ('ctypes', 'winreg', 'fcntl', 'msvcrt') are never imported

    or called anywhere in src/expedition33_rpc/ except inside core/platform.py.
    """
    platform_file = (SRC_DIR / "core" / "platform.py").resolve()
    py_files = list(SRC_DIR.rglob("*.py"))
    assert py_files, "No python files found in src/expedition33_rpc"

    for py_file in py_files:
        if py_file.resolve() == platform_file:
            continue

        content = py_file.read_text(encoding="utf-8")
        tree = ast.parse(content, filename=str(py_file))

        for node in ast.walk(tree):
            # Check import ctypes, import winreg, etc.
            if isinstance(node, ast.Import):
                for alias in node.names:
                    root_pkg = alias.name.split(".")[0]
                    assert root_pkg not in _LOW_LEVEL_OS_MODULES, (
                        f"Direct import of low-level OS module '{alias.name}' forbidden "
                        f"in {py_file.name}:{node.lineno}. Route through core.platform."
                    )

            # Check from ctypes import ..., from winreg import ..., etc.
            if isinstance(node, ast.ImportFrom) and node.module:
                root_pkg = node.module.split(".")[0]
                assert root_pkg not in _LOW_LEVEL_OS_MODULES, (
                    f"Direct import from low-level OS module '{node.module}' forbidden "
                    f"in {py_file.name}:{node.lineno}. Route through core.platform."
                )

            # Check calls on low-level modules if accessed as attributes (e.g. ctypes.something())
            if isinstance(node, ast.Call):
                func = node.func
                if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name):
                    assert func.value.id not in _LOW_LEVEL_OS_MODULES, (
                        f"Low-level OS module call '{func.value.id}.{func.attr}' forbidden "
                        f"in {py_file.name}:{node.lineno}. Route through core.platform."
                    )


def test_bridge_state_provider_no_sleep_in_hot_loop() -> None:
    """Verifies that BridgeStateProvider in detection/detector.py does not invoke time.sleep()."""
    detector_file = SRC_DIR / "detection" / "detector.py"
    assert detector_file.exists()
    content = detector_file.read_text(encoding="utf-8")
    tree = ast.parse(content, filename=str(detector_file))

    bridge_provider_classes: list[ast.ClassDef] = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.ClassDef) and node.name == "BridgeStateProvider"
    ]
    assert bridge_provider_classes, "BridgeStateProvider class definition not found in detector.py"

    for cls_node in bridge_provider_classes:
        for node in ast.walk(cls_node):
            if isinstance(node, ast.Call):
                func = node.func
                # Detect time.sleep(...)
                if (
                    isinstance(func, ast.Attribute)
                    and func.attr == "sleep"
                    and isinstance(func.value, ast.Name)
                    and func.value.id == "time"
                ):
                    pytest.fail(
                        f"Anti-jitter violation: time.sleep() called inside BridgeStateProvider "
                        f"at line {node.lineno}"
                    )
                # Detect direct sleep(...)
                if isinstance(func, ast.Name) and func.id == "sleep":
                    pytest.fail(
                        f"Anti-jitter violation: sleep() called inside BridgeStateProvider "
                        f"at line {node.lineno}"
                    )


def _has_party_fields_or_usage(tree: ast.AST) -> list[str]:
    """Scan an AST tree for definitions, annotations, arguments or attribute usages of party_id / party_size."""
    violations: list[str] = []
    party_names = frozenset({"party_id", "party_size"})

    for node in ast.walk(tree):
        # 1. Class attribute or field definitions (AnnAssign or Assign)
        if (
            isinstance(node, ast.AnnAssign)
            and isinstance(node.target, ast.Name)
            and node.target.id in party_names
        ):
            violations.append(f"Field annotation '{node.target.id}' at line {node.lineno}")
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id in party_names:
                    violations.append(f"Assignment to '{target.id}' at line {node.lineno}")

        # 2. Function parameter definitions
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for arg in node.args.posonlyargs + node.args.args + node.args.kwonlyargs:
                if arg.arg in party_names:
                    violations.append(
                        f"Parameter '{arg.arg}' in function '{node.name}' at line {node.lineno}"
                    )

        # 3. Keyword arguments in function calls
        if isinstance(node, ast.Call):
            for kw in node.keywords:
                if kw.arg in party_names:
                    violations.append(f"Keyword argument '{kw.arg}' at line {node.lineno}")

        # 4. Attribute access (e.g. payload.party_id)
        if isinstance(node, ast.Attribute) and node.attr in party_names:
            violations.append(f"Attribute access '.{node.attr}' at line {node.lineno}")

    return violations


def test_yagni_contract_no_party_id_or_size() -> None:
    """Asserisce che PresencePayload in core/presence.py e DiscordIPCClient.set_activity /

    DiscordRPCManager in integrations/discord_rpc.py non dichiarino né utilizzino i campi
    'party_id' o 'party_size'.
    """
    presence_file = SRC_DIR / "core" / "presence.py"
    discord_rpc_file = SRC_DIR / "integrations" / "discord_rpc.py"

    assert presence_file.exists(), f"File missing: {presence_file}"
    assert discord_rpc_file.exists(), f"File missing: {discord_rpc_file}"

    presence_tree = ast.parse(
        presence_file.read_text(encoding="utf-8"), filename=str(presence_file)
    )
    discord_tree = ast.parse(
        discord_rpc_file.read_text(encoding="utf-8"), filename=str(discord_rpc_file)
    )

    presence_violations = _has_party_fields_or_usage(presence_tree)
    discord_violations = _has_party_fields_or_usage(discord_tree)

    all_violations = [f"{presence_file.name}: {v}" for v in presence_violations] + [
        f"{discord_rpc_file.name}: {v}" for v in discord_violations
    ]

    assert not all_violations, "YAGNI violation: party_id / party_size detected:\n" + "\n".join(
        all_violations
    )
