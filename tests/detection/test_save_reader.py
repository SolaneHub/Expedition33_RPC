from pathlib import Path

import pytest

from expedition33_rpc.detection.save_reader import SaveFileReader


@pytest.mark.unit
def test_save_reader_zone_matching() -> None:
    reader = SaveFileReader()
    assert (
        reader.is_checkpoint_for_zone(
            "LevelMain_EsquieNest",
            "Level.SpawnPoint.EsquieNest.Francois",
            "LevelMain_EsquieNest",
            "Esquie's Nest",
        )
        is True
    )
    assert (
        reader.is_checkpoint_for_zone(
            "Level_Side_VersosDraft",
            "Level.SpawnPoint.VersosDraft.CandyLand",
            "Level_Side_VersosDraft",
            "Verso's Drafts",
        )
        is True
    )
    # Continent and Menu must never match
    assert (
        reader.is_checkpoint_for_zone(
            "Level_WorldMap",
            "Level.SpawnPoint.EsquieNest.Francois",
            "Level_WorldMap",
            "The Continent",
        )
        is False
    )


@pytest.mark.unit
def test_save_reader_parses_real_binary_save(tmp_path: Path) -> None:
    profile_dir = tmp_path / "76561198097793146"
    profile_dir.mkdir(parents=True)
    sav_file = profile_dir / "EXPEDITION_0.sav"

    payload = (
        b"\x00" * 100
        + b"LastUsedSavePoint\x00\x0f\x00\x00\x00StructProperty\x00\x02\x00\x00\x00"
        + b"LevelAssetName\x00\r\x00\x00\x00NameProperty\x00\x00\x00\x00\x00Level_Side_VersosDraft\x00"
        + b"SpawnPointTag\x00Level.SpawnPoint.VersosDraft.CandyLand\x00"
        + b"\x00" * 100
    )
    sav_file.write_bytes(payload)

    reader = SaveFileReader(base_save_dir=tmp_path)
    lvl, tag = reader.read_checkpoint_from_save(str(profile_dir))
    assert lvl == "Level_Side_VersosDraft"
    assert tag == "Level.SpawnPoint.VersosDraft.CandyLand"

    resolved = reader.resolve_checkpoint_for_zone("Level_Side_VersosDraft")
    assert resolved == "Level.SpawnPoint.VersosDraft.CandyLand"
