"""Unit tests for new harness doubles, clock determinism, and fuzz generators."""

from __future__ import annotations

import threading
import urllib.error

import pytest
from tests.harness import (
    DualClockHarness,
    FakeBrowserLauncher,
    FakeHttpOpener,
    FakeHttpResponse,
    FakeWinreg,
    GameSessionSimulator,
    generate_adversarial_bridge_payloads,
    generate_adversarial_discord_frames,
    generate_multilingual_presence_inputs,
    generate_mutated_sav_blobs,
)

from expedition33_rpc.detection.game_data import ALL_SUPPORTED_LANGUAGES


@pytest.mark.unit
def test_fake_winreg_operations() -> None:
    reg = FakeWinreg(
        initial={
            (FakeWinreg.HKEY_CURRENT_USER, r"Software\Test"): {"Val": ("hello", FakeWinreg.REG_SZ)}
        }
    )
    with reg.OpenKey(FakeWinreg.HKEY_CURRENT_USER, r"Software\Test") as key:
        val, reg_type = reg.QueryValueEx(key, "Val")
        assert val == "hello"
        assert reg_type == FakeWinreg.REG_SZ
        reg.SetValueEx(key, "NewVal", 0, FakeWinreg.REG_SZ, "world")
        assert reg.QueryValueEx(key, "NewVal") == ("world", FakeWinreg.REG_SZ)
        reg.DeleteValue(key, "NewVal")
        with pytest.raises(FileNotFoundError):
            reg.QueryValueEx(key, "NewVal")

    reg.open_error = PermissionError("Denied")
    with pytest.raises(PermissionError):
        reg.OpenKey(FakeWinreg.HKEY_CURRENT_USER, r"Software\Test")


@pytest.mark.unit
def test_fake_http_opener_and_browser_launcher() -> None:
    resp = FakeHttpResponse({"tag_name": "v1.2.3"}, status=200)
    opener = FakeHttpOpener(response=resp)
    with opener("https://example.com", timeout=5.0) as r:
        assert r.status == 200
        assert b"v1.2.3" in r.read()
    assert opener.calls == [("https://example.com", 5.0)]

    err_opener = FakeHttpOpener(error=FakeHttpOpener.make_http_error("https://x", 404))
    with pytest.raises(urllib.error.HTTPError):
        err_opener("https://x")

    ev = threading.Event()
    ev.set()
    blocking_opener = FakeHttpOpener(response=resp, block_event=ev)
    with blocking_opener("https://example.com") as r:
        assert r.status == 200

    launcher = FakeBrowserLauncher(return_value=True)
    assert launcher("https://github.com") is True
    assert launcher.opened_urls == ["https://github.com"]


@pytest.mark.unit
def test_game_session_simulator_deterministic_clock(tmp_path: object) -> None:
    from pathlib import Path

    clock = DualClockHarness(initial_monotonic=100.0, initial_epoch=1_700_000_000.0)
    session = GameSessionSimulator(base_dir=Path(str(tmp_path)), clock=clock)
    assert session.proc_start_time == 1_700_000_000.0
    session.start_game().enter_zone("Level_Main_OldLumiere")
    state = session.get_game_state()
    assert state.is_running is True


@pytest.mark.unit
def test_fuzz_generators_are_deterministic() -> None:
    assert generate_adversarial_discord_frames(10, seed=42) == generate_adversarial_discord_frames(
        10, seed=42
    )
    assert generate_adversarial_bridge_payloads(
        10, seed=42
    ) == generate_adversarial_bridge_payloads(10, seed=42)
    assert generate_mutated_sav_blobs(10, seed=42) == generate_mutated_sav_blobs(10, seed=42)
    multilingual = generate_multilingual_presence_inputs(seed=42)
    assert len(multilingual) == len(ALL_SUPPORTED_LANGUAGES)
    assert multilingual == generate_multilingual_presence_inputs(seed=42)
