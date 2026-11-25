"""Bridge mod contract inspector and schema verifier.

Extracts the embedded Lua mod (main.lua) from bridge.zip and parses its tokens
to ensure perfect bidirectional schema alignment with BridgeStateProvider.
"""

from __future__ import annotations

import re
import zipfile
from pathlib import Path
from typing import Any

from expedition33_rpc.core.resources import get_resource_path
from expedition33_rpc.detection.detector import BridgeStateProvider


class BridgeContractInspector:
    """Inspects and validates the contracts between the UE4SS bridge mod and BridgeStateProvider."""

    DEFAULT_SCRIPT_PATH: str = "ue4ss/Mods/Expedition33RPC/scripts/main.lua"

    def __init__(self, bridge_zip_path: str | Path | None = None) -> None:
        if bridge_zip_path is None:
            self.bridge_zip_path = Path(get_resource_path("bridge.zip"))
        else:
            self.bridge_zip_path = Path(bridge_zip_path)

    def read_mod_script(self, script_path: str = DEFAULT_SCRIPT_PATH) -> str:
        """Extracts and decodes the Lua script directly from the bridge.zip asset."""
        if not self.bridge_zip_path.is_file():
            raise FileNotFoundError(f"bridge.zip not found at {self.bridge_zip_path}")
        with zipfile.ZipFile(self.bridge_zip_path, "r") as z:
            return z.read(script_path).decode("utf-8")

    def extract_write_status_format_template(self, lua_content: str | None = None) -> str:
        """Extracts the JSON format string template used inside write_status in main.lua."""
        content = lua_content if lua_content is not None else self.read_mod_script()
        match = re.search(r"local payload = string\.format\(\s*\'([^\']+)\'", content)
        if not match:
            raise ValueError(
                "Failed to locate 'local payload = string.format(' pattern in main.lua"
            )
        return match.group(1).strip()

    def extract_write_status_json_keys(self, lua_content: str | None = None) -> list[str]:
        """Extracts all JSON field keys emitted by write_status in main.lua."""
        template = self.extract_write_status_format_template(lua_content)
        return re.findall(r'"([a-zA-Z0-9_]+)"\s*:', template)

    def extract_write_status_parameters(self, lua_content: str | None = None) -> list[str]:
        """Extracts the formal argument list of write_status function definition in main.lua."""
        content = lua_content if lua_content is not None else self.read_mod_script()
        match = re.search(r"local function write_status\(([^)]*)\)", content)
        if not match:
            raise ValueError("Failed to find 'local function write_status(...)' in main.lua")
        raw_params = match.group(1)
        return [p.strip() for p in raw_params.split(",") if p.strip()]

    def verify_contract_with_provider(
        self,
        sample_payload: dict[str, Any] | None = None,
        now: float = 1_700_000_000.0,
    ) -> tuple[bool, list[str]]:
        """Verifies that all keys emitted by the Lua mod write_status format string are compatible

        with BridgeStateProvider, and tests round-trip parsing.
        Returns (is_valid, list_of_errors).
        """
        errors: list[str] = []
        lua_keys = set(self.extract_write_status_json_keys())

        # Essential keys expected from the Lua bridge telemetry payload
        expected_keys = {
            "in_combat",
            "enemy_name",
            "enemies",
            "zone",
            "raw_zone",
            "raw_level",
            "world_path",
            "checkpoint",
            "floor",
            "tower_floor",
            "tower_trial",
            "timestamp",
        }

        missing = expected_keys - lua_keys
        if missing:
            errors.append(
                f"Lua mod write_status is missing expected telemetry keys: {sorted(missing)}"
            )

        payload = sample_payload or {
            "in_combat": True,
            "enemy_name": "Duollistes",
            "enemies": ["Duollistes", "Alpha Gold Chevaliere"],
            "zone": "Level_Main_OldLumiere",
            "raw_zone": "Level_Main_OldLumiere",
            "raw_level": "Level_Main_OldLumiere_P",
            "world_path": "/Game/Maps/OldLumiere",
            "checkpoint": "Entrance",
            "floor": 4,
            "tower_floor": 4,
            "tower_trial": [2, 1],
            "timestamp": now,
        }

        # Verify that sample payload provides all emitted keys
        for k in lua_keys:
            if k not in payload:
                errors.append(f"Sample payload missing key '{k}' emitted by Lua write_status")

        # Test ingestion with BridgeStateProvider test double / provider
        class InlineBridgeProvider(BridgeStateProvider):
            def read_bridge_status(self) -> dict[str, Any] | None:
                return payload

        provider = InlineBridgeProvider(epoch_provider=lambda: now)
        data = provider.read_game_data(min_valid_timestamp=now - 5.0)
        if data is None:
            errors.append("BridgeStateProvider failed to process sample payload (returned None)")
        else:
            if data.get("in_combat") != payload.get("in_combat"):
                errors.append("Mismatch in 'in_combat' parsed value")
            if data.get("raw_zone") != (payload.get("raw_zone") or payload.get("zone")):
                errors.append("Mismatch in 'raw_zone' parsed value")
            if data.get("enemy_name") != payload.get("enemy_name"):
                errors.append("Mismatch in 'enemy_name' parsed value")
            if data.get("checkpoint") != payload.get("checkpoint"):
                errors.append("Mismatch in 'checkpoint' parsed value")

        return len(errors) == 0, errors

    def verify_lua_structure(self, lua_content: str | None = None) -> tuple[bool, list[str]]:
        """Performs structural safety checks on main.lua."""
        content = lua_content if lua_content is not None else self.read_mod_script()
        errors: list[str] = []

        # 1. Check json_escape handles required characters
        escape_match = re.search(r"local function json_escape\(s\)(.*?)\nend", content, re.DOTALL)
        if not escape_match:
            errors.append("Missing 'local function json_escape(s)' in main.lua")
        else:
            escape_body = escape_match.group(1)
            for token in (r'"\\"', """'"'""", r'"\n"', r'"\r"', r'"\t"', r"[%z\1-\31]"):
                if token not in escape_body:
                    errors.append(f"json_escape is missing handling for {token}")

        # 2. Check write_status cleans up tmp_path
        write_match = re.search(r"local function write_status\((.*?)\nend", content, re.DOTALL)
        if not write_match:
            errors.append("Missing 'local function write_status(...)' in main.lua")
        else:
            write_body = write_match.group(1)
            if "tmp_path" in write_body and "os.remove(tmp_path)" not in write_body:
                errors.append("write_status uses tmp_path without os.remove(tmp_path) cleanup")

        # 3. Check continuous heartbeat LoopAsync(1000, ...)
        if not re.search(r"LoopAsync\(\s*1000\s*,", content):
            errors.append("Missing continuous heartbeat LoopAsync(1000, ...) in main.lua")

        # 4. Check no direct UObject queries inside LoopAsync outside ExecuteInGameThread
        loop_match = re.search(r"LoopAsync\(\s*1000\s*,(.*)\Z", content, re.DOTALL)
        if loop_match:
            loop_body = loop_match.group(1)
            stripped_exec = re.sub(
                r"ExecuteInGameThread\(function\(\).*?\n\s*end\)",
                "",
                loop_body,
                flags=re.DOTALL,
            )
            for unsafe_call in ("FindAllOf(", "StaticFindObject("):
                if unsafe_call in stripped_exec:
                    errors.append(
                        f"Direct UObject call {unsafe_call!r} found in LoopAsync outside ExecuteInGameThread"
                    )

        # 5. Check balanced block openers vs 'end' (excluding comments and strings)
        cleaned = re.sub(r"--[^\n]*", "", content)
        cleaned = re.sub(r"'[^'\n]*'", "''", cleaned)
        cleaned = re.sub(r'"[^"\n]*"', '""', cleaned)
        openers = len(re.findall(r"\b(?:function|if|for|while)\b", cleaned))
        closers = len(re.findall(r"\bend\b", cleaned))
        if openers != closers:
            errors.append(
                f"Unbalanced Lua blocks: {openers} openers (function/if/for/while) vs {closers} 'end'"
            )

        return len(errors) == 0, errors
