"""Tests for SaveFileReader binary UE .sav parsing and heuristics."""

from __future__ import annotations

from pathlib import Path

import pytest
from tests.harness import SaveFixtureBuilder

from expedition33_rpc.detection.save_reader import SaveFileReader

pytestmark = pytest.mark.integration


@pytest.fixture
def save_env(tmp_path: Path) -> tuple[Path, SaveFileReader]:
    save_dir = tmp_path / "SaveGames"
    save_dir.mkdir(parents=True)
    reader = SaveFileReader(base_save_dir=str(save_dir))
    return save_dir, reader


def test_read_zone_from_saves_lastmap_str_property(save_env: tuple[Path, SaveFileReader]) -> None:
    save_dir, reader = save_env
    SaveFixtureBuilder.container().with_last_map(
        zone_name="Level_Main_OldLumiere", slot_suffix="Current_01"
    ).with_raw_bytes(b"TrailingFooterBytes\x01\x02\x03").write_saves_container(save_dir)

    zone = reader.read_zone_from_saves(str(save_dir))
    assert zone == "Level_Main_OldLumiere"


def test_read_zone_from_saves_fallback_levels(save_env: tuple[Path, SaveFileReader]) -> None:
    save_dir, reader = save_env
    SaveFixtureBuilder.container().with_raw_bytes(b"BinaryNoise").with_fallback_level(
        "Level_Forest"
    ).with_fallback_level("SideLevel_SpringMeadows").with_fallback_level(
        "SmallLevel_AncientCave"
    ).write_saves_container(save_dir)

    zone = reader.read_zone_from_saves(str(save_dir))
    assert zone == "SmallLevel_AncientCave"


def test_read_zone_from_saves_fallback_worldmap(save_env: tuple[Path, SaveFileReader]) -> None:
    save_dir, reader = save_env
    SaveFixtureBuilder.container().with_world_map().with_raw_bytes(b"Data").write_saves_container(
        save_dir
    )

    zone = reader.read_zone_from_saves(str(save_dir))
    assert zone == "WorldMap"


def test_read_zone_from_saves_corrupt_lastmap_falls_back_to_level_regex(
    save_env: tuple[Path, SaveFileReader],
) -> None:
    save_dir, reader = save_env
    SaveFixtureBuilder.container().with_corrupt_last_map(
        invalid_tag="InvalidPropertyTag"
    ).with_fallback_level("Level_Forest").write_saves_container(save_dir)

    zone = reader.read_zone_from_saves(str(save_dir))
    assert zone == "Level_Forest"


def test_read_zone_from_saves_filters_streaming_levels_and_picks_primary_map(
    save_env: tuple[Path, SaveFileReader],
) -> None:
    save_dir, reader = save_env
    SaveFixtureBuilder.container().with_corrupt_last_map(
        invalid_tag="InvalidPropertyTag"
    ).with_fallback_level("Level_OldLumiere_Lighting").with_fallback_level(
        "Level_OldLumiere_Audio"
    ).with_fallback_level("Level_Main_OldLumiere").with_fallback_level(
        "Level_OldLumiere_Stream_02"
    ).with_fallback_level("Level_OldLumiere_VFX").write_saves_container(save_dir)

    zone = reader.read_zone_from_saves(str(save_dir))
    assert zone == "Level_Main_OldLumiere"


def test_read_zone_from_saves_prioritizes_main_map_over_sublevels(
    save_env: tuple[Path, SaveFileReader],
) -> None:
    save_dir, reader = save_env
    SaveFixtureBuilder.container().with_raw_bytes(b"BinaryNoise").with_fallback_level(
        "SideLevel_Cave"
    ).with_fallback_level("Level_Forest_HLOD").with_fallback_level(
        "Level_Main_FlyingManor"
    ).with_fallback_level("SmallLevel_Room").write_saves_container(save_dir)

    zone = reader.read_zone_from_saves(str(save_dir))
    assert zone == "Level_Main_FlyingManor"


def test_read_zone_from_saves_truncated_stream(save_env: tuple[Path, SaveFileReader]) -> None:
    save_dir, reader = save_env
    full_bytes = SaveFixtureBuilder.container().with_last_map("Level_Main_OldLumiere").build()
    truncated_bytes = full_bytes[: len(full_bytes) // 2]
    (save_dir / "SavesContainer.sav").write_bytes(truncated_bytes)

    zone = reader.read_zone_from_saves(str(save_dir))
    assert zone is None


def test_read_zone_from_saves_no_match(save_env: tuple[Path, SaveFileReader]) -> None:
    save_dir, reader = save_env
    SaveFixtureBuilder.container().with_raw_bytes(
        b"RandomUnrelatedBytesWithoutTokens\xff\xfe"
    ).write_saves_container(save_dir)

    zone = reader.read_zone_from_saves(str(save_dir))
    assert zone is None


def test_read_zone_from_saves_missing_file(save_env: tuple[Path, SaveFileReader]) -> None:
    save_dir, reader = save_env
    zone = reader.read_zone_from_saves(str(save_dir))
    assert zone is None


def test_read_checkpoint_from_save_synthetic_binary(
    save_env: tuple[Path, SaveFileReader],
) -> None:
    save_dir, reader = save_env
    SaveFixtureBuilder.expedition_slot().with_savepoint(
        level_name="Level_AbbestCave",
        spawn_point_tag="Level.SpawnPoint.AbbestCave.Arena",
    ).write_expedition_slot(save_dir, slot=0)

    lvl, tag = reader.read_checkpoint_from_save(str(save_dir))
    assert lvl == "Level_AbbestCave"
    assert tag == "Level.SpawnPoint.AbbestCave.Arena"


def test_read_checkpoint_from_save_truncated_stream(
    save_env: tuple[Path, SaveFileReader],
) -> None:
    save_dir, reader = save_env
    full_bytes = (
        SaveFixtureBuilder.expedition_slot()
        .with_savepoint("Level_AbbestCave", "Level.SpawnPoint.AbbestCave.Arena")
        .build()
    )
    idx = full_bytes.find(b"LastUsedSavePoint") + len(b"LastUsedSavePoint") + 5
    (save_dir / "EXPEDITION_0.sav").write_bytes(full_bytes[:idx])

    lvl, tag = reader.read_checkpoint_from_save(str(save_dir))
    assert lvl is None
    assert tag is None


def test_read_checkpoint_from_save_missing_or_corrupt(
    save_env: tuple[Path, SaveFileReader],
) -> None:
    save_dir, reader = save_env
    lvl, tag = reader.read_checkpoint_from_save(str(save_dir))
    assert lvl is None
    assert tag is None

    SaveFixtureBuilder.expedition_slot().with_raw_bytes(
        b"NoCheckpointTagHere"
    ).write_expedition_slot(save_dir, slot=0)
    lvl2, tag2 = reader.read_checkpoint_from_save(str(save_dir))
    assert lvl2 is None
    assert tag2 is None


def test_is_checkpoint_for_zone_main_menu_suppression() -> None:
    reader = SaveFileReader()
    assert not reader.is_checkpoint_for_zone(
        "Level_MainMenu", "Level.SpawnPoint.SomePoint", "MainMenu", "Main Menu"
    )
    assert not reader.is_checkpoint_for_zone(
        "Level_Bootstrap", "Level.SpawnPoint.SomePoint", "Bootstrap", "Nel menu principale"
    )
    assert not reader.is_checkpoint_for_zone(
        "Level_WorldMap", "Level.SpawnPoint.SomePoint", "WorldMap", "The Continent"
    )


def test_read_checkpoint_from_save_selects_latest_modified_slot(
    save_env: tuple[Path, SaveFileReader],
) -> None:
    save_dir, reader = save_env
    SaveFixtureBuilder.expedition_slot().with_savepoint(
        level_name="Level_Old", spawn_point_tag="Level.SpawnPoint.Old"
    ).write_expedition_slot(save_dir, slot=0, mtime=1000.0)

    SaveFixtureBuilder.expedition_slot().with_savepoint(
        level_name="Level_New", spawn_point_tag="Level.SpawnPoint.New"
    ).write_expedition_slot(save_dir, slot=1, mtime=2000.0)

    lvl, tag = reader.read_checkpoint_from_save(str(save_dir))
    assert lvl == "Level_New"
    assert tag == "Level.SpawnPoint.New"


def test_real_gvas_fixture_on_disk() -> None:
    fixtures_root = Path(__file__).resolve().parents[1] / "harness" / "fixtures"
    if (fixtures_root / "saves").is_dir():
        fixtures_root = fixtures_root / "saves"
    if not fixtures_root.is_dir():
        pytest.skip("Fixtures directory not found")

    reader = SaveFileReader(base_save_dir=str(fixtures_root))
    latest_dir = reader.get_latest_save_dir()
    assert latest_dir is not None

    zone = reader.read_zone_from_saves(latest_dir)
    assert zone == "Level_Main_OldLumiere"

    lvl, tag = reader.read_checkpoint_from_save(latest_dir)
    assert lvl == "Level_Main_OldLumiere"
    assert tag == "Level.SpawnPoint.ManorGardens"
    assert reader.is_checkpoint_for_zone(lvl, tag, zone or "", "Old Lumiere") is True


def test_read_checkpoint_from_save_caches_result_and_invalidates_on_change(
    save_env: tuple[Path, SaveFileReader],
) -> None:
    save_dir, reader = save_env
    SaveFixtureBuilder.expedition_slot().with_savepoint(
        level_name="Level_Initial", spawn_point_tag="Level.SpawnPoint.Initial"
    ).write_expedition_slot(save_dir, slot=0, mtime=1000.0)

    # 1. First read populates cache
    lvl1, tag1 = reader.read_checkpoint_from_save(str(save_dir))
    assert lvl1 == "Level_Initial"
    assert tag1 == "Level.SpawnPoint.Initial"

    sav_file = str(save_dir / "EXPEDITION_0.sav")
    assert sav_file in reader._checkpoint_cache
    cached_entry = reader._checkpoint_cache[sav_file]
    assert cached_entry[2] == ("Level_Initial", "Level.SpawnPoint.Initial")

    # 2. Corrupt or delete file content in memory: cache hit returns without disk parsing
    # Overwrite cache with a sentinel value to prove it does not re-parse the file
    reader._checkpoint_cache[sav_file] = (
        cached_entry[0],
        cached_entry[1],
        ("Cached_Level", "Cached_Tag"),
    )
    lvl_cached, tag_cached = reader.read_checkpoint_from_save(str(save_dir))
    assert lvl_cached == "Cached_Level"
    assert tag_cached == "Cached_Tag"

    # 3. File modification (newer mtime) invalidates cache and triggers re-read
    SaveFixtureBuilder.expedition_slot().with_savepoint(
        level_name="Level_Updated", spawn_point_tag="Level.SpawnPoint.Updated"
    ).write_expedition_slot(save_dir, slot=0, mtime=2000.0)

    lvl_updated, tag_updated = reader.read_checkpoint_from_save(str(save_dir))
    assert lvl_updated == "Level_Updated"
    assert tag_updated == "Level.SpawnPoint.Updated"
    assert reader._checkpoint_cache[sav_file][2] == ("Level_Updated", "Level.SpawnPoint.Updated")


def test_read_zone_from_saves_caches_result_and_invalidates_on_change(
    save_env: tuple[Path, SaveFileReader],
) -> None:
    save_dir, reader = save_env
    SaveFixtureBuilder.container().with_last_map("Level_ZoneA").write_saves_container(save_dir)

    # 1. First read populates zone cache
    zone1 = reader.read_zone_from_saves(str(save_dir))
    assert zone1 == "Level_ZoneA"

    container_path = str(save_dir / "SavesContainer.sav")
    assert container_path in reader._zone_cache
    st_tuple = reader._zone_cache[container_path]
    assert st_tuple[2] == "Level_ZoneA"

    # 2. Modify cache entry to verify cache hit avoids disk parsing
    reader._zone_cache[container_path] = (st_tuple[0], st_tuple[1], "CachedZone")
    assert reader.read_zone_from_saves(str(save_dir)) == "CachedZone"

    # 3. Modify container file to invalidate cache
    SaveFixtureBuilder.container().with_last_map("Level_ZoneB").write_saves_container(save_dir)
    assert reader.read_zone_from_saves(str(save_dir)) == "Level_ZoneB"
    assert reader._zone_cache[container_path][2] == "Level_ZoneB"
