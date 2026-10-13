"""Unit tests for tools/simulate_telemetry.py developer CLI tool."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest
from tools.simulate_telemetry import main, write_telemetry


@pytest.mark.unit
def test_write_telemetry_atomic_and_schema(tmp_path: Path) -> None:
    target_file = tmp_path / "expedition33_status.json"
    payload = write_telemetry(
        file_path=target_file,
        zone="Level_Main_OldLumiere",
        in_combat=True,
        enemy_name="Duollistes",
        floor=12,
        checkpoint="Gate",
    )

    assert target_file.is_file()
    read_data = json.loads(target_file.read_text(encoding="utf-8"))

    assert read_data["zone"] == "Level_Main_OldLumiere"
    assert read_data["in_combat"] is True
    assert read_data["enemy_name"] == "Duollistes"
    assert read_data["floor"] == 12
    assert read_data["checkpoint"] == "Gate"
    assert "timestamp" in read_data
    assert read_data["timestamp"] == payload["timestamp"]


@pytest.mark.unit
def test_write_telemetry_non_combat_clears_enemy(tmp_path: Path) -> None:
    target_file = tmp_path / "expedition33_status.json"
    payload = write_telemetry(
        file_path=target_file,
        zone="Level_Sirene_Main_V2",
        in_combat=False,
        enemy_name="Duollistes",
    )

    assert target_file.is_file()
    assert payload["in_combat"] is False
    assert payload["enemy_name"] == ""
    assert payload["enemies"] == []


@pytest.mark.unit
def test_write_telemetry_with_explicit_enemies(tmp_path: Path) -> None:
    target_file = tmp_path / "expedition33_status.json"
    enemies = ["Alpha Francois", "Duollistes"]
    payload = write_telemetry(
        file_path=target_file,
        zone="Level_EndlessTower",
        in_combat=True,
        enemy_name="Alpha Francois, Duollistes",
        floor=5,
        enemies=enemies,
    )

    assert target_file.is_file()
    read_data = json.loads(target_file.read_text(encoding="utf-8"))
    assert read_data["enemies"] == enemies
    assert read_data["enemies"] == payload["enemies"]
    assert read_data["floor"] == 5
    assert read_data["in_combat"] is True


@pytest.mark.unit
def test_simulate_telemetry_cli_main_write(tmp_path: Path) -> None:
    target_file = tmp_path / "expedition33_status.json"
    cli_args = [
        "simulate_telemetry.py",
        "--zone",
        "Level_Custom_Abyss",
        "--combat",
        "--enemy",
        "AbyssWatcher",
        "--enemies",
        "AbyssWatcher",
        "Phantom",
        "--floor",
        "99",
        "--checkpoint",
        "Sanctum",
        "--path",
        str(target_file),
    ]

    with patch("sys.argv", cli_args):
        main()

    assert target_file.is_file()
    data = json.loads(target_file.read_text(encoding="utf-8"))
    assert data["zone"] == "Level_Custom_Abyss"
    assert data["in_combat"] is True
    assert data["enemy_name"] == "AbyssWatcher"
    assert data["enemies"] == ["AbyssWatcher", "Phantom"]
    assert data["floor"] == 99
    assert data["checkpoint"] == "Sanctum"


@pytest.mark.unit
def test_simulate_telemetry_cli_main_clean(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    target_file = tmp_path / "expedition33_status.json"
    target_file.write_text("{}", encoding="utf-8")
    assert target_file.exists()

    cli_args = ["simulate_telemetry.py", "--clean", "--path", str(target_file)]
    with patch("sys.argv", cli_args):
        main()

    assert not target_file.exists()
    out = capsys.readouterr().out
    assert "Removed telemetry file" in out

    # Test clean on non-existent file
    with patch("sys.argv", cli_args):
        main()
    out_missing = capsys.readouterr().out
    assert "does not exist" in out_missing


@pytest.mark.unit
def test_simulate_telemetry_cli_non_combat(tmp_path: Path) -> None:
    target_file = tmp_path / "expedition33_status.json"
    cli_args = [
        "simulate_telemetry.py",
        "--zone",
        "Level_Sirene_Hub",
        "--enemy",
        "IgnoreMe",
        "--checkpoint",
        "Camp",
        "--path",
        str(target_file),
    ]

    with patch("sys.argv", cli_args):
        main()

    assert target_file.is_file()
    data = json.loads(target_file.read_text(encoding="utf-8"))
    assert data["zone"] == "Level_Sirene_Hub"
    assert data["in_combat"] is False
    assert data["enemy_name"] == ""
    assert data["enemies"] == []
    assert data["checkpoint"] == "Camp"


@pytest.mark.unit
def test_simulate_telemetry_cli_loop(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    target_file = tmp_path / "expedition33_status.json"
    cli_args = [
        "simulate_telemetry.py",
        "--zone",
        "Level_Loop_Test",
        "--loop",
        "--interval",
        "0.1",
        "--path",
        str(target_file),
    ]

    with (
        patch("sys.argv", cli_args),
        patch("time.sleep", side_effect=KeyboardInterrupt),
    ):
        main()

    assert target_file.is_file()
    data = json.loads(target_file.read_text(encoding="utf-8"))
    assert data["zone"] == "Level_Loop_Test"
    out = capsys.readouterr().out
    assert "Refreshing telemetry every 0.1s" in out
    assert "Simulation stopped." in out
