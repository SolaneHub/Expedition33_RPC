"""Testing harness and mock utilities for Expedition33_RPC."""

from tests.harness.discord_pipe import DiscordPipeSimulator
from tests.harness.discord_transport_mock import MockDiscordServer
from tests.harness.fake_process import FakeProcess
from tests.harness.game_session import GameSessionSimulator, create_telemetry_payload
from tests.harness.tray_harness import HeadlessTrayHarness

__all__ = [
    "DiscordPipeSimulator",
    "FakeProcess",
    "GameSessionSimulator",
    "HeadlessTrayHarness",
    "MockDiscordServer",
    "create_telemetry_payload",
]
