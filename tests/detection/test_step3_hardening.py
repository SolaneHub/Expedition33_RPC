"""Challenge round tests for Step 3: Hot-path I/O, clock decoupling, and Tier 0-3 hardening."""

from __future__ import annotations

import json
from pathlib import Path
from types import MappingProxyType
from typing import Any, cast

import pytest
from tests.harness.fake_process import FakeProcess

from expedition33_rpc.detection.detector import BridgeStateProvider, GameDetector
from expedition33_rpc.detection.game_data import (
    get_game_data,
    get_zone_name_overrides_by_lang,
)
from expedition33_rpc.detection.steam_resolver import SteamCompatResolver
from expedition33_rpc.detection.timer_tracker import ZoneTimerTracker


@pytest.mark.unit
def test_zone_timer_ntp_jump_without_now_monotonic() -> None:
    """NTP jumps of +-3600s must not contaminate _combat_start_monotonic when now_monotonic is omitted."""
    tracker = ZoneTimerTracker()
    tracker.update("Zone A", in_combat=False, now_epoch=1000.0)
    tracker.update("Zone A", in_combat=True, now_epoch=1010.0)

    # _combat_start_monotonic must come from time.monotonic(), not 1010.0
    assert tracker._combat_start_monotonic is not None
    assert tracker._combat_start_monotonic != 1010.0

    # Negative NTP jump (-3600s) and positive NTP jump (+3600s)
    tracker.update("Zone A", in_combat=False, now_epoch=1010.0 - 3600.0)
    assert tracker.zone_paused_duration >= 0.0
    assert tracker.zone_paused_duration < 10.0


@pytest.mark.unit
def test_bridge_state_provider_hostile_tower_payloads(tmp_path: Path) -> None:
    """Bool tower_floor and non-int tower_trial must be safely rejected without crashing."""
    telemetry_file = tmp_path / "status.json"
    provider = BridgeStateProvider(
        paths=[str(telemetry_file)],
        epoch_provider=lambda: 1000.0,
    )

    payload = {
        "timestamp": 1000.0,
        "zone": "Endless Tower",
        "in_combat": True,
        "tower_floor": True,
        "tower_trial": ["not_an_int", "also_bad"],
    }
    telemetry_file.write_text(json.dumps(payload), encoding="utf-8")
    data = provider.read_game_data()
    assert data is not None
    assert data["tower_floor"] is None
    assert data["tower_trial"] is None

    payload["tower_trial"] = [True, 2]
    telemetry_file.write_text(json.dumps(payload), encoding="utf-8")
    data2 = provider.read_game_data()
    assert data2 is not None
    assert data2["tower_trial"] is None


@pytest.mark.unit
def test_pid_reuse_invalidates_stale_paths(tmp_path: Path) -> None:
    """When a PID is reused with a different create_time and exe_path, cached paths must update."""
    dir_a = tmp_path / "install_a" / "Sandfall" / "Binaries" / "Win64"
    dir_b = tmp_path / "install_b" / "Sandfall" / "Binaries" / "Win64"
    dir_a.mkdir(parents=True)
    dir_b.mkdir(parents=True)
    exe_a = dir_a / "Sandfall-Win64-Shipping.exe"
    exe_b = dir_b / "Sandfall-Win64-Shipping.exe"

    proc_a = FakeProcess(
        pid=4242,
        name="Sandfall-Win64-Shipping.exe",
        exe_path=str(exe_a),
        create_time=100.0,
    )
    proc_b = FakeProcess(
        pid=4242,
        name="Sandfall-Win64-Shipping.exe",
        exe_path=str(exe_b),
        create_time=200.0,
    )

    current_proc = [proc_a]
    detector = GameDetector(
        process_scanner=lambda: list(current_proc),
        bridge_provider=None,
    )

    detector.get_game_state(now_monotonic=1.0, now_epoch=1000.0)
    assert detector.game_exe_path == str(exe_a)
    assert detector.game_win64_dir == dir_a

    # Simulate PID reuse
    current_proc[0] = proc_b
    detector.get_game_state(now_monotonic=2.0, now_epoch=1001.0)
    assert detector.game_exe_path == str(exe_b)
    assert detector.game_win64_dir == dir_b


@pytest.mark.unit
def test_steam_resolver_proton_sd_card_and_windows_env(tmp_path: Path) -> None:
    """Proton prefixes must include secondary Steam libraries from libraryfolders.vdf, and _expand_win_env must use self._environ."""
    steam_root = tmp_path / ".local" / "share" / "Steam"
    steamapps = steam_root / "steamapps"
    steamapps.mkdir(parents=True)
    sd_lib = tmp_path / "run" / "media" / "mmcblk0p1" / "SteamLibrary"
    (steamapps / "libraryfolders.vdf").write_text(
        f'"libraryfolders"\n{{\n  "1"\n  {{\n    "path" "{sd_lib}"\n  }}\n}}\n',
        encoding="utf-8",
    )

    resolver_linux = SteamCompatResolver(
        is_windows=False,
        home_dir=tmp_path,
        environ={},
        winreg_module=None,
    )
    prefixes = resolver_linux.get_proton_prefixes()
    expected_sd_pfx = sd_lib / "steamapps" / "compatdata" / resolver_linux.app_id / "pfx"
    assert expected_sd_pfx in prefixes

    resolver_win = SteamCompatResolver(
        is_windows=True,
        environ={"TEMP": r"C:\CustomTemp", "LOCALAPPDATA": r"C:\CustomLocal"},
        winreg_module=None,
    )
    candidates = resolver_win.resolve_telemetry_candidates()
    assert r"C:\CustomTemp\expedition33_status.json" in candidates
    assert r"C:\CustomLocal\Sandfall\rpc_status.json" in candidates


@pytest.mark.unit
def test_game_data_cache_clear_and_immutability() -> None:
    """get_game_data.cache_clear() must invalidate derived snapshots, and returned mappings must be immutable."""
    overrides_1 = get_zone_name_overrides_by_lang()
    assert isinstance(overrides_1, MappingProxyType)
    with pytest.raises(TypeError):
        cast(Any, overrides_1)["en"] = {}

    get_game_data.cache_clear()
    overrides_2 = get_zone_name_overrides_by_lang()
    assert overrides_1 is not overrides_2
    assert overrides_1 == overrides_2
