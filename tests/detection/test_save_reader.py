from pathlib import Path

import pytest

from expedition33_rpc.detection.detector import SaveReaderProtocol
from expedition33_rpc.detection.save_reader import SaveFileReader


@pytest.mark.unit
def test_save_file_reader_implements_protocol() -> None:
    reader = SaveFileReader()
    assert isinstance(reader, SaveReaderProtocol)


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


@pytest.mark.unit
def test_save_reader_empty_save_file(tmp_path: Path) -> None:
    profile_dir = tmp_path / "76561198097793146"
    profile_dir.mkdir(parents=True)
    empty_sav = profile_dir / "EXPEDITION_0.sav"
    empty_sav.write_bytes(b"")

    reader = SaveFileReader(base_save_dir=tmp_path)
    lvl, tag = reader.read_checkpoint_from_save(str(profile_dir))
    assert lvl is None
    assert tag is None
    assert reader.resolve_checkpoint_for_zone("Level_Side_VersosDraft") == ""


@pytest.mark.unit
def test_save_reader_linux_cross_platform_path(tmp_path: Path) -> None:
    fake_home = tmp_path / "home" / "deck"
    steam_compat = (
        fake_home / ".local" / "share" / "Steam" / "steamapps" / "compatdata" / "1903340" / "pfx"
    )
    save_dir = (
        steam_compat
        / "drive_c"
        / "users"
        / "steamuser"
        / "AppData"
        / "Local"
        / "Sandfall"
        / "Saved"
        / "SaveGames"
    )
    save_dir.mkdir(parents=True)

    from expedition33_rpc.detection.compat_paths import resolve_user_data_path

    resolved = resolve_user_data_path(is_windows=False, home_dir=fake_home)
    assert Path(resolved).resolve() == save_dir.resolve()


@pytest.mark.unit
def test_save_reader_semantic_aliases_all() -> None:
    reader = SaveFileReader()
    # 1. Monolith / Paintress
    assert (
        reader.is_checkpoint_for_zone(
            "Level_Monolith", "Level.SpawnPoint.Paintress", "Level_Monolith", "The Monolith"
        )
        is True
    )
    # 2. Manor / Flyinghouse
    assert (
        reader.is_checkpoint_for_zone(
            "Level_Manor", "Level.SpawnPoint.FlyingHouse", "Level_Manor", "The Manor"
        )
        is True
    )
    # 3. Chroma / Sunless
    assert (
        reader.is_checkpoint_for_zone(
            "Level_ChromaZone", "Level.SpawnPoint.Chroma", "Level_Sunless", "Sunless Shore"
        )
        is True
    )
    # 4. Yellow / Harvest
    assert (
        reader.is_checkpoint_for_zone(
            "Level_YellowForest", "Level.SpawnPoint.Yellow", "Level_Harvest", "Harvest Realm"
        )
        is True
    )
    # 5. Reacher / Scalatore
    assert (
        reader.is_checkpoint_for_zone(
            "Level_Reacher", "Level.SpawnPoint.Reacher", "Level_Reacher", "Scalatore"
        )
        is True
    )
    # 6. Seacliff / Stone Wave
    assert (
        reader.is_checkpoint_for_zone(
            "Level_SeaCliff", "Level.SpawnPoint.SeaCliff", "Level_StoneWave", "Stone Wave"
        )
        is True
    )
    # 7. Goblu / Flying Waters
    assert (
        reader.is_checkpoint_for_zone(
            "Level_Goblu", "Level.SpawnPoint.Goblu", "Level_FlyingWaters", "Flying Waters"
        )
        is True
    )


@pytest.mark.unit
def test_save_reader_corrupt_or_partial_binary_save(tmp_path: Path) -> None:
    profile_dir = tmp_path / "12345"
    profile_dir.mkdir(parents=True)
    sav_file = profile_dir / "EXPEDITION_0.sav"

    # 1. Payload with no LastUsedSavePoint
    sav_file.write_bytes(b"\x00" * 500)
    reader = SaveFileReader(base_save_dir=tmp_path)
    lvl, tag = reader.read_checkpoint_from_save(str(profile_dir))
    assert lvl is None
    assert tag is None

    # 2. Payload with LastUsedSavePoint near the EOF (< 4096 bytes)
    payload_near_eof = (
        b"\x00" * 10
        + b"LastUsedSavePoint\x00\x0f\x00\x00\x00StructProperty\x00\x02\x00\x00\x00"
        + b"LevelAssetName\x00\r\x00\x00\x00NameProperty\x00\x00\x00\x00\x00Level_Short\x00"
        + b"SpawnPointTag\x00Level.SpawnPoint.Short.Tag\x00"
        + b"\x00" * 10
    )
    sav_file.write_bytes(payload_near_eof)
    reader.reset()
    lvl, tag = reader.read_checkpoint_from_save(str(profile_dir))
    assert lvl == "Level_Short"
    assert tag == "Level.SpawnPoint.Short.Tag"

    # 3. Cache hit: verify cached result is returned without re-parsing
    sav_str = str(sav_file)
    assert sav_str in reader._checkpoint_cache
    cached_entry = reader._checkpoint_cache[sav_str]
    reader._checkpoint_cache[sav_str] = (
        cached_entry[0],
        cached_entry[1],
        ("CachedLevel", "CachedTag"),
    )
    lvl_cached, tag_cached = reader.read_checkpoint_from_save(str(profile_dir))
    assert lvl_cached == "CachedLevel"
    assert tag_cached == "CachedTag"
