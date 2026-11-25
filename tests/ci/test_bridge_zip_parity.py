"""CI parity and deterministic repack tests for bridge/scripts/main.lua and bridge.zip."""

from __future__ import annotations

import hashlib
import shutil
import zipfile
from pathlib import Path

import pytest
from tests.harness.bridge_contract_verifier import BridgeContractInspector
from tools.build_bridge_zip import (
    DEFAULT_LUA_PATH,
    DEFAULT_ZIP_PATH,
    PRESERVED_ENTRIES,
    check_bridge_zip,
    rebuild_bridge_zip,
)


@pytest.mark.unit
def test_bridge_main_lua_matches_zip_and_structure() -> None:
    """Fast unit check: bridge/scripts/main.lua matches bridge.zip and passes structural checks."""
    assert check_bridge_zip(zip_path=DEFAULT_ZIP_PATH, lua_path=DEFAULT_LUA_PATH) == 0

    inspector = BridgeContractInspector(DEFAULT_ZIP_PATH)
    lua_content = DEFAULT_LUA_PATH.read_text(encoding="utf-8")

    ok_struct, struct_errors = inspector.verify_lua_structure(lua_content)
    assert ok_struct, f"Lua structural errors: {struct_errors}"

    ok_contract, contract_errors = inspector.verify_contract_with_provider()
    assert ok_contract, f"Lua contract errors: {contract_errors}"


@pytest.mark.integration
def test_build_bridge_zip_roundtrip_preserves_binaries(tmp_path: Path) -> None:
    """Integration check: rebuild_bridge_zip repacks deterministically and preserves binaries."""
    tmp_zip = tmp_path / "bridge.zip"
    tmp_lua = tmp_path / "main.lua"
    shutil.copy2(DEFAULT_ZIP_PATH, tmp_zip)
    shutil.copy2(DEFAULT_LUA_PATH, tmp_lua)

    with zipfile.ZipFile(tmp_zip, "r") as zf:
        before_hashes = {
            entry: hashlib.sha256(zf.read(entry)).hexdigest() for entry in PRESERVED_ENTRIES
        }

    # Modify main.lua in tmp_path -> check_bridge_zip must fail
    original_lua = tmp_lua.read_text(encoding="utf-8")
    tmp_lua.write_text(original_lua + "\n-- roundtrip test marker\n", encoding="utf-8")
    assert check_bridge_zip(zip_path=tmp_zip, lua_path=tmp_lua) == 1

    # Rebuild -> check_bridge_zip must pass and preserved binaries must be byte-for-byte identical
    assert rebuild_bridge_zip(zip_path=tmp_zip, lua_path=tmp_lua) == 0
    assert check_bridge_zip(zip_path=tmp_zip, lua_path=tmp_lua) == 0

    with zipfile.ZipFile(tmp_zip, "r") as zf:
        after_hashes = {
            entry: hashlib.sha256(zf.read(entry)).hexdigest() for entry in PRESERVED_ENTRIES
        }
    assert after_hashes == before_hashes
