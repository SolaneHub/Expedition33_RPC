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
    """Verifies that time.monotonic is never assigned/serialized to outbound Discord timestamps in presentation.py or core/presence.py."""
    for rel_path in ("ui/presentation.py", "core/presence.py"):
        target_file = SRC_DIR / rel_path
        assert target_file.exists()
        content = target_file.read_text(encoding="utf-8")
        tree = ast.parse(content, filename=str(target_file))

        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                for kw in node.keywords:
                    if kw.arg in _FORBIDDEN_TIMESTAMP_TARGETS:
                        for child in ast.walk(kw.value):
                            assert not _is_time_monotonic(child), (
                                f"Forbidden monotonic assigned to {kw.arg} in {target_file}:{node.lineno}"
                            )

            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name) and target.id in _FORBIDDEN_TIMESTAMP_TARGETS:
                        for child in ast.walk(node.value):
                            assert not _is_time_monotonic(child), (
                                f"Forbidden monotonic assigned to {target.id} in {target_file}:{node.lineno}"
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


def test_anti_busy_spin_no_sleep_zero() -> None:
    """Scansiona l'intero albero src/expedition33_rpc/ e asserisce che non vi siano chiamate a time.sleep(0)."""
    violations: list[str] = []
    py_files = list(SRC_DIR.rglob("*.py"))
    assert py_files, "No python files found in src/expedition33_rpc"

    for py_file in py_files:
        content = py_file.read_text(encoding="utf-8")
        tree = ast.parse(content, filename=str(py_file))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                func = node.func
                is_sleep = False
                if (
                    (
                        isinstance(func, ast.Attribute)
                        and func.attr == "sleep"
                        and isinstance(func.value, ast.Name)
                        and func.value.id == "time"
                    )
                    or isinstance(func, ast.Name)
                    and func.id == "sleep"
                ):
                    is_sleep = True

                if is_sleep and node.args:
                    first_arg = node.args[0]
                    if isinstance(first_arg, ast.Constant) and first_arg.value == 0:
                        rel_path = py_file.relative_to(SRC_DIR)
                        violations.append(
                            f"{rel_path}:{node.lineno} calls sleep(0) which causes busy-spinning"
                        )

    assert not violations, "Anti-busy-spin violation(s) found:\n" + "\n".join(violations)


def test_layer_boundary_normalization_purity() -> None:
    """Asserisce che detection/normalization.py non contenga alcun import (nemmeno locale o condizionale)

    di GameState o di moduli appartenenti a ui o core.
    """
    norm_file = SRC_DIR / "detection" / "normalization.py"
    assert norm_file.exists(), f"File missing: {norm_file}"
    content = norm_file.read_text(encoding="utf-8")
    tree = ast.parse(content, filename=str(norm_file))

    violations: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                parts = alias.name.split(".")
                if any(p in ("ui", "core") for p in parts):
                    violations.append(f"Import of {alias.name} at line {node.lineno}")
                if "GameState" in alias.name:
                    violations.append(f"Import of GameState in {alias.name} at line {node.lineno}")

        if isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            parts = mod.split(".")
            if any(p in ("ui", "core") for p in parts):
                violations.append(f"ImportFrom from '{mod}' at line {node.lineno}")
            for alias in node.names:
                if alias.name == "GameState":
                    violations.append(f"ImportFrom GameState from '{mod}' at line {node.lineno}")

    assert not violations, f"Layer boundary violations in {norm_file.name}:\n" + "\n".join(
        violations
    )


def test_clock_decoupling_bridge_and_rpc_manager() -> None:
    """Asserisce che in DiscordRPCManager.connect() e BridgeStateProvider tutti i riferimenti orari

    usino i provider iniettati e mai chiamate dirette a time.time() su logiche di intervallo/deadline.
    """
    # 1. Check DiscordRPCManager.connect() in integrations/discord_rpc.py
    discord_file = SRC_DIR / "integrations" / "discord_rpc.py"
    assert discord_file.exists()
    discord_tree = ast.parse(discord_file.read_text(encoding="utf-8"), filename=str(discord_file))

    for node in ast.walk(discord_tree):
        if isinstance(node, ast.ClassDef) and node.name == "DiscordRPCManager":
            for item in node.body:
                if (
                    isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef))
                    and item.name == "connect"
                ):
                    for sub in ast.walk(item):
                        if isinstance(sub, ast.Call) and _is_time_time(sub.func):
                            pytest.fail(
                                f"Direct call to time.time() in DiscordRPCManager.connect() at line {sub.lineno}"
                            )

    # 2. Check BridgeStateProvider in detection/detector.py
    detector_file = SRC_DIR / "detection" / "detector.py"
    assert detector_file.exists()
    detector_tree = ast.parse(
        detector_file.read_text(encoding="utf-8"), filename=str(detector_file)
    )

    for node in ast.walk(detector_tree):
        if isinstance(node, ast.ClassDef) and node.name == "BridgeStateProvider":
            for item in node.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    # Allow __init__ default value time.time
                    for sub in ast.walk(item):
                        if isinstance(sub, ast.Call) and _is_time_time(sub.func):
                            pytest.fail(
                                f"Direct call to time.time() inside BridgeStateProvider.{item.name} at line {sub.lineno}"
                            )


def test_orchestrator_imports_no_symbols_from_ui() -> None:
    """Verifies that core/orchestrator.py never imports any symbols from expedition33_rpc.ui."""
    orch_file = SRC_DIR / "core" / "orchestrator.py"
    assert orch_file.exists()
    tree = ast.parse(orch_file.read_text(encoding="utf-8"), filename=str(orch_file))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert not alias.name.startswith("expedition33_rpc.ui"), (
                    f"Forbidden UI import in orchestrator: {alias.name}"
                )
        if isinstance(node, ast.ImportFrom) and node.module:
            assert not node.module.startswith("expedition33_rpc.ui"), (
                f"Forbidden UI import from in orchestrator: {node.module}"
            )


def test_strict_acyclic_import_dag() -> None:
    """Gate 1: Scans recursively all files in src/expedition33_rpc/ via ast.parse and

    verifies that the directed module dependency graph is a strict DAG without any cycles.
    """
    all_py = list(SRC_DIR.rglob("*.py"))
    assert all_py, "No python files found in src/expedition33_rpc"

    mod_to_file: dict[str, Path] = {}
    file_to_mod: dict[Path, str] = {}
    for p in all_py:
        rel = p.relative_to(SRC_DIR).with_suffix("")
        parts = list(rel.parts)
        if parts[-1] == "__init__":
            parts.pop()
        mod_name = "expedition33_rpc" + (("." + ".".join(parts)) if parts else "")
        mod_to_file[mod_name] = p
        file_to_mod[p] = mod_name

    graph: dict[str, set[str]] = {m: set() for m in mod_to_file}

    for py_file, cur_mod in file_to_mod.items():
        tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
        cur_pkg = cur_mod if py_file.name == "__init__.py" else cur_mod.rpartition(".")[0]

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    name = alias.name
                    if name.startswith("expedition33_rpc"):
                        matched: str | None = None
                        for m in mod_to_file:
                            if (name == m or name.startswith(m + ".")) and (
                                matched is None or len(m) > len(matched)
                            ):
                                matched = m
                        if matched and matched != cur_mod:
                            graph[cur_mod].add(matched)
            elif isinstance(node, ast.ImportFrom):
                if node.level > 0:
                    parts = cur_pkg.split(".")
                    level = node.level
                    if level <= len(parts):
                        base = ".".join(parts[: len(parts) - level + 1])
                        full = f"{base}.{node.module}" if node.module else base
                    else:
                        full = ""
                else:
                    full = node.module or ""

                if full.startswith("expedition33_rpc"):
                    matched = None
                    for m in mod_to_file:
                        if (full == m or full.startswith(m + ".")) and (
                            matched is None or len(m) > len(matched)
                        ):
                            matched = m
                    if matched and matched != cur_mod:
                        graph[cur_mod].add(matched)
                    for alias in node.names:
                        cand = f"{full}.{alias.name}"
                        if cand in mod_to_file and cand != cur_mod:
                            graph[cur_mod].add(cand)

    visited: dict[str, int] = {}
    cycle: list[str] = []

    def dfs(node: str, path: list[str]) -> bool:
        visited[node] = 1
        path.append(node)
        for neighbor in sorted(graph[node]):
            if visited.get(neighbor) == 1:
                cycle_start = path.index(neighbor)
                cycle.extend(path[cycle_start:] + [neighbor])
                return True
            if visited.get(neighbor) != 2 and dfs(neighbor, path):
                return True
        path.pop()
        visited[node] = 2
        return False

    for m in sorted(graph):
        if m not in visited and dfs(m, []):
            break

    assert not cycle, f"Cycle detected in import graph: {' -> '.join(cycle)}"


def test_layer_boundary_enforcement() -> None:
    """Gate 2: Asserts that no file in core/ imports any module from ui/

    and that no file in integrations/ imports from expedition33_rpc.__init__.
    """
    core_dir = SRC_DIR / "core"
    integrations_dir = SRC_DIR / "integrations"
    assert core_dir.is_dir() and integrations_dir.is_dir()

    violations: list[str] = []

    # 1. core/ must not import from ui/ (exclude app.py and smoke.py which serve as application entrypoints)
    exempt_core_files = {"app.py", "smoke.py"}
    for py_file in core_dir.rglob("*.py"):
        if py_file.name in exempt_core_files:
            continue
        tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.startswith("expedition33_rpc.ui") or alias.name == "ui":
                        violations.append(
                            f"{py_file.name}:{node.lineno} imports forbidden UI module '{alias.name}'"
                        )
            elif isinstance(node, ast.ImportFrom):
                mod = node.module or ""
                if mod.startswith("expedition33_rpc.ui") or mod == "ui":
                    violations.append(
                        f"{py_file.name}:{node.lineno} imports from forbidden UI module '{mod}'"
                    )

    # 2. integrations/ must not import from expedition33_rpc.__init__
    for py_file in integrations_dir.rglob("*.py"):
        tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name == "expedition33_rpc":
                        violations.append(
                            f"{py_file.name}:{node.lineno} imports from expedition33_rpc root package"
                        )
            elif (
                isinstance(node, ast.ImportFrom)
                and node.level == 0
                and node.module == "expedition33_rpc"
            ):
                violations.append(
                    f"{py_file.name}:{node.lineno} imports from expedition33_rpc root package"
                )

    assert not violations, "Layer boundary violations found:\n" + "\n".join(violations)


def test_no_zombie_shims_or_spec_files() -> None:
    """Gate 3: Asserts that compat_paths.py does not exist in src/

    and that no *.spec file exists in repo root or tracked in git.
    """
    repo_root = SRC_DIR.parents[1]

    # Check compat_paths.py in src/
    compat_files = list(SRC_DIR.rglob("compat_paths.py"))
    assert not compat_files, f"Zombie shim compat_paths.py found: {compat_files}"

    # Check *.spec files in repo root
    root_spec_files = list(repo_root.glob("*.spec"))
    assert not root_spec_files, f"Spec files found in root: {root_spec_files}"

    # Verify no *.spec file is tracked in git (via git ls-files if git available, or checking git index)
    try:
        import subprocess

        res = subprocess.run(
            ["git", "ls-files", "*.spec"],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            check=False,
        )
        if res.returncode == 0:
            tracked = [line.strip() for line in res.stdout.splitlines() if line.strip()]
            assert not tracked, f"Tracked .spec files in git: {tracked}"
    except (FileNotFoundError, PermissionError):
        pass


def test_clock_naming_uniformity() -> None:
    """Gate 4: Verifies via AST that in classes (BridgeStateProvider, GameDetector,

    AppOrchestrator, DiscordRPCManager) time parameters are named strictly
    'monotonic_provider' and 'epoch_provider', with no ambiguous 'time_provider' parameter.
    """
    target_classes = {
        "BridgeStateProvider",
        "GameDetector",
        "AppOrchestrator",
        "DiscordRPCManager",
    }
    found_classes: set[str] = set()

    for py_file in SRC_DIR.rglob("*.py"):
        tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and node.name in target_classes:
                found_classes.add(node.name)
                for item in node.body:
                    if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        all_params = [arg.arg for arg in item.args.args + item.args.kwonlyargs]
                        assert "time_provider" not in all_params, (
                            f"Ambiguous parameter 'time_provider' found in {node.name}.{item.name} at {py_file.name}:{item.lineno}"
                        )
                        for param in all_params:
                            if "provider" in param and param not in (
                                "monotonic_provider",
                                "epoch_provider",
                                "bridge_provider",
                            ):
                                pytest.fail(
                                    f"Unexpected provider parameter '{param}' in {node.name}.{item.name} at {py_file.name}:{item.lineno}"
                                )

    assert found_classes == target_classes, (
        f"Missing classes in AST search: {target_classes - found_classes}"
    )


def test_orchestrator_stop_monotonic_decoupling() -> None:
    """Gate 5: Asserts that AppOrchestrator.stop does not invoke time.monotonic() directly,

    but uses the injected monotonic_provider.
    """
    orch_file = SRC_DIR / "core" / "orchestrator.py"
    assert orch_file.exists()
    tree = ast.parse(orch_file.read_text(encoding="utf-8"), filename=str(orch_file))

    found_stop = False
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == "AppOrchestrator":
            for item in node.body:
                if isinstance(item, ast.FunctionDef) and item.name == "stop":
                    found_stop = True
                    for sub in ast.walk(item):
                        if isinstance(sub, ast.Call) and _is_time_monotonic(sub.func):
                            pytest.fail(
                                f"Direct time.monotonic() call found in AppOrchestrator.stop at {orch_file.name}:{sub.lineno}"
                            )

    assert found_stop, "AppOrchestrator.stop method not found in AST"
