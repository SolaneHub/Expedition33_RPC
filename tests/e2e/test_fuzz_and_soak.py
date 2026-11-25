"""Fuzz and soak tests for wire codecs, telemetry ingestion, save parsing, and orchestrator chaos."""

from __future__ import annotations

import contextlib
import json
import struct
import threading
from pathlib import Path

import pytest
from tests.harness.discord_pipe import DiscordPipeSimulator
from tests.harness.fuzz_generators import (
    generate_adversarial_bridge_payloads,
    generate_adversarial_discord_frames,
    generate_multilingual_presence_inputs,
    generate_mutated_sav_blobs,
)
from tests.harness.orchestrator_chaos_harness import OrchestratorChaosHarness

from expedition33_rpc.core.presence import build_presence_payload
from expedition33_rpc.detection.detector import BridgeStateProvider, GameState
from expedition33_rpc.detection.save_reader import SaveFileReader
from expedition33_rpc.integrations.discord_rpc import DiscordFrameCodec, DiscordIPCClient


def _run_discord_frame_fuzz(count: int, seed: int) -> None:
    frames = generate_adversarial_discord_frames(count=count, seed=seed)
    for raw in frames:
        if len(raw) >= 8:
            with contextlib.suppress(
                ValueError, struct.error, json.JSONDecodeError, UnicodeDecodeError
            ):
                _opcode, _payload = DiscordFrameCodec.decode(raw)
        pipe = DiscordPipeSimulator()
        client = DiscordIPCClient(client_id="1234567890")
        client.transport = pipe
        client.close()


def _run_bridge_payload_fuzz(tmp_path: Path, count: int, seed: int) -> None:
    tmp_path.mkdir(parents=True, exist_ok=True)
    bridge_file = tmp_path / "expedition33_status.json"
    provider = BridgeStateProvider(paths=[str(bridge_file)])
    payloads = generate_adversarial_bridge_payloads(count=count, seed=seed)
    for payload in payloads:
        bridge_file.write_text(json.dumps(payload), encoding="utf-8")
        result = provider.read_bridge_status()
        assert result is None or isinstance(result, dict)


def _run_sav_blob_fuzz(tmp_path: Path, count: int, seed: int) -> None:
    save_dir = tmp_path / "SaveGames"
    save_dir.mkdir(parents=True, exist_ok=True)
    save_file = save_dir / "FuzzSave_0.sav"
    reader = SaveFileReader(base_save_dir=save_dir)
    blobs = generate_mutated_sav_blobs(count=count, seed=seed)
    for blob in blobs:
        save_file.write_bytes(blob)
        result = reader.get_latest_save_dir()
        assert result is None or isinstance(result, str)


@pytest.mark.integration
def test_fuzz_discord_frame_codec_and_ipc_client() -> None:
    _run_discord_frame_fuzz(count=50, seed=33)


@pytest.mark.integration
def test_fuzz_bridge_state_provider(tmp_path: Path) -> None:
    _run_bridge_payload_fuzz(tmp_path, count=50, seed=33)


@pytest.mark.integration
def test_fuzz_save_file_reader(tmp_path: Path) -> None:
    _run_sav_blob_fuzz(tmp_path, count=50, seed=33)


@pytest.mark.integration
def test_fuzz_multilingual_presence_length_invariants() -> None:
    inputs = generate_multilingual_presence_inputs(seed=33)
    assert len(inputs) == 20
    for item in inputs:
        state = GameState(
            is_running=True,
            process_pid=1234,
            zone_name=str(item.get("zone_name", "")),
            in_combat=bool(item.get("in_combat", False)),
            game_language=str(item.get("language", "en")),
        )
        payload = build_presence_payload(state)
        for field in (payload.details, payload.state, payload.large_text):
            if field is not None:
                assert len(field) <= 127
                assert len(field.encode("utf-8")) <= 128


@pytest.mark.soak
def test_soak_fuzz_500_iterations_and_orchestrator_chaos(tmp_path: Path) -> None:
    before_threads = {t.ident for t in threading.enumerate()}
    _run_discord_frame_fuzz(count=500, seed=33)
    _run_bridge_payload_fuzz(tmp_path / "bridge", count=500, seed=33)
    _run_sav_blob_fuzz(tmp_path / "sav", count=500, seed=33)

    chaos = OrchestratorChaosHarness(tmp_path / "chaos")
    chaos.run_chaos_cycles(cycles=100, seed=33)

    after_threads = [
        t
        for t in threading.enumerate()
        if t.ident not in before_threads and t.is_alive() and not t.daemon
    ]
    assert not after_threads, f"Orphaned threads detected: {after_threads}"
