"""CI test validating packaging parity between physical assets, build script, and smoke test."""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SRC_ASSETS_DIR = PROJECT_ROOT / "src" / "expedition33_rpc" / "assets"
BUILD_SCRIPT = PROJECT_ROOT / "build_exe.py"
SMOKE_SCRIPT = PROJECT_ROOT / "src" / "expedition33_rpc" / "core" / "smoke.py"


def _get_physical_assets() -> list[str]:
    """Retrieves all asset filenames present in src/expedition33_rpc/assets/."""
    assert SRC_ASSETS_DIR.exists() and SRC_ASSETS_DIR.is_dir()
    return sorted(f.name for f in SRC_ASSETS_DIR.iterdir() if f.is_file())


def _extract_build_exe_assets() -> set[str]:
    """Extracts asset filenames referenced in build_exe.py (--add-data and --icon)."""
    assert BUILD_SCRIPT.exists()
    content = BUILD_SCRIPT.read_text(encoding="utf-8")
    tree = ast.parse(content, filename=str(BUILD_SCRIPT))

    referenced_assets: set[str] = set()
    asset_pattern = re.compile(r"assets[/\\]([A-Za-z0-9_.-]+)")

    # Search for string literals in the PyInstaller cmd list
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            for match in asset_pattern.finditer(node.value):
                referenced_assets.add(match.group(1))
        elif isinstance(node, ast.JoinedStr):
            # Formatted strings, e.g. f"src/expedition33_rpc/assets/icon.png{os.pathsep}..."
            for part in node.values:
                if isinstance(part, ast.Constant) and isinstance(part.value, str):
                    for match in asset_pattern.finditer(part.value):
                        referenced_assets.add(match.group(1))

    return referenced_assets


def _extract_smoke_assets() -> set[str]:
    """Extracts asset filenames checked in core/smoke.py."""
    assert SMOKE_SCRIPT.exists()
    content = SMOKE_SCRIPT.read_text(encoding="utf-8")
    tree = ast.parse(content, filename=str(SMOKE_SCRIPT))

    checked_assets: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            # Look for get_resource_path("...")
            func = node.func
            if (
                (isinstance(func, ast.Name) and func.id == "get_resource_path")
                or (isinstance(func, ast.Attribute) and func.attr == "get_resource_path")
            ) and (
                node.args
                and isinstance(node.args[0], ast.Constant)
                and isinstance(node.args[0].value, str)
            ):
                checked_assets.add(node.args[0].value)

    return checked_assets


def test_build_packaging_parity_physical_assets_in_build_script() -> None:
    """Asserisce che ogni file presente nella cartella fisica src/expedition33_rpc/assets/

    (icon.png, icon.ico, bridge.zip, game_data.json) sia esplicitamente incluso tra gli argomenti
    --add-data o --icon in build_exe.py.
    """
    physical_assets = _get_physical_assets()
    build_assets = _extract_build_exe_assets()

    assert "icon.png" in physical_assets
    assert "icon.ico" in physical_assets
    assert "bridge.zip" in physical_assets
    assert "game_data.json" in physical_assets

    missing_in_build = set(physical_assets) - build_assets
    assert not missing_in_build, (
        f"Assets present in physical directory but missing from build_exe.py packaging: {missing_in_build}"
    )


def test_build_packaging_parity_smoke_verifies_all_assets() -> None:
    """Asserisce che core/smoke.py verifichi l'esistenza a runtime di tutti gli asset inclusi nel bundle."""
    physical_assets = _get_physical_assets()
    smoke_assets = _extract_smoke_assets()

    missing_in_smoke = set(physical_assets) - smoke_assets
    assert not missing_in_smoke, (
        f"Assets bundled but not validated in core/smoke.py: {missing_in_smoke}"
    )


def test_build_exe_entrypoint_and_specpath() -> None:
    """Verifica che build_exe.py punti a src/expedition33_rpc/__main__.py e passi --specpath build."""
    assert BUILD_SCRIPT.exists()
    content = BUILD_SCRIPT.read_text(encoding="utf-8")
    tree = ast.parse(content, filename=str(BUILD_SCRIPT))

    cmd_constants: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            cmd_constants.append(node.value)

    assert "src/expedition33_rpc/__main__.py" in cmd_constants, (
        "build_exe.py must target src/expedition33_rpc/__main__.py as entrypoint"
    )
    assert "--specpath" in cmd_constants, "build_exe.py must pass --specpath"
    idx = cmd_constants.index("--specpath")
    assert idx + 1 < len(cmd_constants) and cmd_constants[idx + 1] == "build", (
        "build_exe.py must set --specpath to build"
    )
    assert "main.py" not in cmd_constants, "build_exe.py must not reference legacy main.py"
