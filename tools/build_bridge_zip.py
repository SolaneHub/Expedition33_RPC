"""Deterministic build and parity check tool for src/expedition33_rpc/assets/bridge.zip."""

from __future__ import annotations

import argparse
import hashlib
import os
import sys
import zipfile
from pathlib import Path

EXPECTED_ENTRIES: tuple[str, ...] = (
    "dwmapi.dll",
    "ue4ss/UE4SS-settings.ini",
    "ue4ss/UE4SS.dll",
    "ue4ss/Mods/mods.txt",
    "ue4ss/Mods/Expedition33RPC/scripts/main.lua",
)

LUA_ENTRY = "ue4ss/Mods/Expedition33RPC/scripts/main.lua"
PRESERVED_ENTRIES: tuple[str, ...] = tuple(e for e in EXPECTED_ENTRIES if e != LUA_ENTRY)
FIXED_ZIP_DATE_TIME: tuple[int, int, int, int, int, int] = (2025, 1, 1, 0, 0, 0)

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_ZIP_PATH = REPO_ROOT / "src" / "expedition33_rpc" / "assets" / "bridge.zip"
DEFAULT_LUA_PATH = REPO_ROOT / "bridge" / "scripts" / "main.lua"


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _validate_zip_entries(names: list[str]) -> list[str]:
    errors: list[str] = []
    for name in names:
        if name.startswith("/") or "\\" in name or ".." in Path(name).parts:
            errors.append(f"Unsafe zip entry path detected: {name!r}")

    name_set = set(names)
    expected_set = set(EXPECTED_ENTRIES)

    missing = sorted(expected_set - name_set)
    if missing:
        errors.append(f"Missing expected zip entries: {missing}")

    extra = sorted(name_set - expected_set)
    if extra:
        errors.append(f"Unexpected zip entries: {extra}")

    return errors


def check_bridge_zip(zip_path: Path = DEFAULT_ZIP_PATH, lua_path: Path = DEFAULT_LUA_PATH) -> int:
    """Verify without writing that bridge.zip matches bridge/scripts/main.lua and has valid entries."""
    if not zip_path.is_file():
        print(f"ERROR: bridge.zip not found at {zip_path}", file=sys.stderr)
        return 1
    if not lua_path.is_file():
        print(f"ERROR: main.lua not found at {lua_path}", file=sys.stderr)
        return 1

    expected_lua_bytes = lua_path.read_bytes()

    with zipfile.ZipFile(zip_path, "r") as zf:
        names = zf.namelist()
        errors = _validate_zip_entries(names)
        if errors:
            for err in errors:
                print(f"ERROR: {err}", file=sys.stderr)
            return 1

        zip_lua_bytes = zf.read(LUA_ENTRY)
        if zip_lua_bytes != expected_lua_bytes:
            print(
                f"ERROR: {LUA_ENTRY} inside {zip_path} does not match {lua_path} "
                f"(zip sha256={_sha256(zip_lua_bytes)}, disk sha256={_sha256(expected_lua_bytes)})",
                file=sys.stderr,
            )
            return 1

    print(f"OK: {zip_path} is in sync with {lua_path} (sha256={_sha256(expected_lua_bytes)})")
    return 0


def rebuild_bridge_zip(zip_path: Path = DEFAULT_ZIP_PATH, lua_path: Path = DEFAULT_LUA_PATH) -> int:
    """Deterministically repack bridge.zip with updated main.lua while preserving other entries."""
    if not zip_path.is_file():
        print(f"ERROR: bridge.zip not found at {zip_path}", file=sys.stderr)
        return 1
    if not lua_path.is_file():
        print(f"ERROR: main.lua not found at {lua_path}", file=sys.stderr)
        return 1

    new_lua_bytes = lua_path.read_bytes()

    preserved_data: dict[str, bytes] = {}
    preserved_hashes_before: dict[str, str] = {}

    with zipfile.ZipFile(zip_path, "r") as zf:
        errors = _validate_zip_entries(zf.namelist())
        if errors:
            for err in errors:
                print(f"ERROR: {err}", file=sys.stderr)
            return 1

        for entry in PRESERVED_ENTRIES:
            raw = zf.read(entry)
            preserved_data[entry] = raw
            preserved_hashes_before[entry] = _sha256(raw)

    all_entries: dict[str, bytes] = {
        **preserved_data,
        LUA_ENTRY: new_lua_bytes,
    }

    tmp_zip_path = zip_path.with_suffix(".zip.tmp")
    try:
        with zipfile.ZipFile(tmp_zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf_out:
            for entry_name in sorted(all_entries):
                info = zipfile.ZipInfo(filename=entry_name, date_time=FIXED_ZIP_DATE_TIME)
                info.compress_type = zipfile.ZIP_DEFLATED
                info.external_attr = 0o644 << 16
                zf_out.writestr(info, all_entries[entry_name])

        with zipfile.ZipFile(tmp_zip_path, "r") as zf_verify:
            for entry in PRESERVED_ENTRIES:
                after_hash = _sha256(zf_verify.read(entry))
                if after_hash != preserved_hashes_before[entry]:
                    raise RuntimeError(
                        f"SHA-256 mismatch for preserved entry {entry}: "
                        f"before={preserved_hashes_before[entry]}, after={after_hash}"
                    )
            if zf_verify.read(LUA_ENTRY) != new_lua_bytes:
                raise RuntimeError(f"SHA-256 mismatch for {LUA_ENTRY} after repack")

        os.replace(tmp_zip_path, zip_path)
    finally:
        if tmp_zip_path.exists():
            tmp_zip_path.unlink()

    zip_sha256 = _sha256(zip_path.read_bytes())
    print(f"REBUILT: {zip_path} (sha256={zip_sha256})")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Deterministic build and parity check tool for bridge.zip"
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument(
        "--check",
        action="store_true",
        help="Verify bridge/scripts/main.lua matches bridge.zip without writing",
    )
    mode.add_argument(
        "--rebuild",
        action="store_true",
        help="Deterministically repack bridge.zip with bridge/scripts/main.lua",
    )
    parser.add_argument(
        "--zip-path",
        type=Path,
        default=DEFAULT_ZIP_PATH,
        help="Path to bridge.zip",
    )
    parser.add_argument(
        "--lua-path",
        type=Path,
        default=DEFAULT_LUA_PATH,
        help="Path to main.lua",
    )

    args = parser.parse_args(argv)
    if args.check:
        return check_bridge_zip(zip_path=args.zip_path, lua_path=args.lua_path)
    return rebuild_bridge_zip(zip_path=args.zip_path, lua_path=args.lua_path)


if __name__ == "__main__":
    raise SystemExit(main())
