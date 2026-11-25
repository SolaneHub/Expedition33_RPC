"""Testing harness and mock utilities for Expedition33_RPC."""

from tests.harness.bridge_contract_verifier import BridgeContractInspector
from tests.harness.clock_harness import DualClockHarness
from tests.harness.discord_pipe import DiscordFaultInjector, DiscordPipeSimulator
from tests.harness.discord_transport_mock import MockDiscordServer
from tests.harness.fake_process import FakeProcess
from tests.harness.fake_services import (
    FakeBridgeInstaller,
    FakeBrowserLauncher,
    FakeHttpOpener,
    FakeHttpResponse,
    FakeStartupService,
    FakeUpdater,
    FakeWinreg,
    FakeWinregKey,
)
from tests.harness.fs_audit import FilesystemActivityAudit
from tests.harness.fuzz_generators import (
    generate_adversarial_bridge_payloads,
    generate_adversarial_discord_frames,
    generate_multilingual_presence_inputs,
    generate_mutated_sav_blobs,
)
from tests.harness.game_session import (
    SCENARIOS,
    GameSessionSimulator,
    StoryboardStep,
    create_telemetry_payload,
)
from tests.harness.orchestrator_chaos_harness import OrchestratorChaosHarness
from tests.harness.save_builder import SaveFileBuilder
from tests.harness.telemetry_contention_simulator import TelemetryContentionSimulator
from tests.harness.tray_harness import HeadlessTrayHarness

__all__ = [
    "SCENARIOS",
    "BridgeContractInspector",
    "DiscordFaultInjector",
    "DiscordPipeSimulator",
    "DualClockHarness",
    "FakeBridgeInstaller",
    "FakeBrowserLauncher",
    "FakeHttpOpener",
    "FakeHttpResponse",
    "FakeProcess",
    "FakeStartupService",
    "FakeUpdater",
    "FakeWinreg",
    "FakeWinregKey",
    "FilesystemActivityAudit",
    "GameSessionSimulator",
    "HeadlessTrayHarness",
    "MockDiscordServer",
    "OrchestratorChaosHarness",
    "SaveFileBuilder",
    "StoryboardStep",
    "TelemetryContentionSimulator",
    "create_telemetry_payload",
    "generate_adversarial_bridge_payloads",
    "generate_adversarial_discord_frames",
    "generate_multilingual_presence_inputs",
    "generate_mutated_sav_blobs",
]
