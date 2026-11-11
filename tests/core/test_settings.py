"""Unit tests for Settings and SettingsService."""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path
from unittest.mock import patch

import pytest

from expedition33_rpc.core.settings import Settings, SettingsService, get_default_settings_dir


@pytest.mark.unit
def test_settings_dataclass_defaults() -> None:
    settings = Settings()
    assert settings.anti_spoiler is False

    custom_settings = Settings(anti_spoiler=True)
    assert custom_settings.anti_spoiler is True


@pytest.mark.unit
def test_settings_service_default_path() -> None:
    service = SettingsService()
    expected_path = get_default_settings_dir() / "settings.json"
    assert service.path == expected_path
    assert service.anti_spoiler is False


@pytest.mark.unit
def test_settings_service_load_nonexistent_file(tmp_path: Path) -> None:
    custom_path = tmp_path / "nonexistent" / "settings.json"
    service = SettingsService(custom_path=custom_path)

    assert service.anti_spoiler is False
    assert service.is_anti_spoiler_enabled() is False
    assert not custom_path.exists()


@pytest.mark.unit
def test_settings_service_load_corrupt_json(tmp_path: Path) -> None:
    custom_path = tmp_path / "corrupted.json"
    custom_path.write_text("{ not valid json !!!", encoding="utf-8")

    service = SettingsService(custom_path=custom_path)
    assert service.anti_spoiler is False
    assert service.load() is False


@pytest.mark.unit
def test_settings_service_save_and_load(tmp_path: Path) -> None:
    custom_path = tmp_path / "settings.json"
    service = SettingsService(custom_path=custom_path)

    service.anti_spoiler = True
    assert service.save() is True
    assert custom_path.is_file()

    # Verify formatting (UTF-8, 2 spaces indent)
    raw_content = custom_path.read_text(encoding="utf-8")
    assert '  "anti_spoiler": true' in raw_content

    # Load back with fresh service
    fresh_service = SettingsService(custom_path=custom_path)
    assert fresh_service.anti_spoiler is True
    assert fresh_service.is_anti_spoiler_enabled() is True


@pytest.mark.unit
def test_settings_service_update(tmp_path: Path) -> None:
    custom_path = tmp_path / "update_settings.json"
    service = SettingsService(custom_path=custom_path)

    assert service.update(anti_spoiler=True) is True
    assert service.anti_spoiler is True

    data = json.loads(custom_path.read_text(encoding="utf-8"))
    assert data["anti_spoiler"] is True

    # Sequential update must persist
    assert service.update(anti_spoiler=False) is True
    data_updated = json.loads(custom_path.read_text(encoding="utf-8"))
    assert data_updated["anti_spoiler"] is False
    assert service.anti_spoiler is False


@pytest.mark.unit
def test_settings_service_preserves_external_keys(tmp_path: Path) -> None:
    custom_path = tmp_path / "ext_settings.json"
    custom_path.write_text(
        json.dumps({"external_key": "preserved_value", "anti_spoiler": False}),
        encoding="utf-8",
    )

    service = SettingsService(custom_path=custom_path)
    assert service.set_anti_spoiler_enabled(True) is True

    data = json.loads(custom_path.read_text(encoding="utf-8"))
    assert data["anti_spoiler"] is True
    assert data["external_key"] == "preserved_value"


@pytest.mark.unit
def test_settings_service_toggle_anti_spoiler(tmp_path: Path) -> None:
    custom_path = tmp_path / "toggle_settings.json"
    service = SettingsService(custom_path=custom_path)

    assert service.toggle_anti_spoiler() is True
    assert service.is_anti_spoiler_enabled() is True

    assert service.toggle_anti_spoiler() is False
    assert service.is_anti_spoiler_enabled() is False


@pytest.mark.unit
def test_settings_service_save_oserror_handling(tmp_path: Path) -> None:
    custom_path = tmp_path / "locked_settings.json"
    service = SettingsService(custom_path=custom_path)
    assert service.set_anti_spoiler_enabled(False) is True

    with patch("pathlib.Path.replace", side_effect=PermissionError("Locked")):
        assert service.set_anti_spoiler_enabled(True) is False

    # In-memory value should roll back on save failure
    assert service.anti_spoiler is False
    assert service.is_anti_spoiler_enabled() is False


@pytest.mark.unit
def test_settings_service_concurrent_updates(tmp_path: Path) -> None:
    import concurrent.futures

    custom_path = tmp_path / "concurrent_settings.json"
    service = SettingsService(custom_path=custom_path)

    def worker(i: int) -> bool:
        return service.update(anti_spoiler=(i % 2 == 0))

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
        results = list(executor.map(worker, range(20)))

    assert all(results)
    assert custom_path.is_file()
    data = json.loads(custom_path.read_text(encoding="utf-8"))
    assert "anti_spoiler" in data


@pytest.mark.unit
def test_settings_service_in_memory_caching_and_atomic_update(tmp_path: Path) -> None:
    custom_json = tmp_path / "cached_settings.json"
    service = SettingsService(custom_path=custom_json)

    # Initial query returns default without requiring a file on disk
    assert not custom_json.exists()
    assert service.is_anti_spoiler_enabled() is False

    # Atomic write updates in-memory cache and writes to file
    success = service.set_anti_spoiler_enabled(True)
    assert success is True
    assert service.is_anti_spoiler_enabled() is True
    assert custom_json.is_file()

    # Black-box cache verification: query succeeds from in-memory cache even if disk file is removed
    custom_json.unlink()
    assert not custom_json.exists()
    assert service.is_anti_spoiler_enabled() is True

    # Toggle updates in-memory cache and persists back to disk
    new_val = service.toggle_anti_spoiler()
    assert new_val is False
    assert service.is_anti_spoiler_enabled() is False
    assert custom_json.is_file()

    # Verify persistence by reading from a fresh service instance
    fresh_service = SettingsService(custom_path=custom_json)
    assert fresh_service.is_anti_spoiler_enabled() is False


@pytest.mark.unit
def test_settings_service_nested_directory_creation_and_recovery(tmp_path: Path) -> None:
    """Verifies that SettingsService creates nested parent directories and recovers if deleted."""
    nested_json = tmp_path / "deep" / "nested" / "dir" / "settings.json"
    assert not nested_json.parent.exists()

    service = SettingsService(custom_path=nested_json)
    assert nested_json.parent.is_dir()
    assert not nested_json.exists()

    assert service.set_anti_spoiler_enabled(True) is True
    assert nested_json.is_file()
    assert service.is_anti_spoiler_enabled() is True

    # Simulate external deletion of parent directory
    shutil.rmtree(tmp_path / "deep")
    assert not nested_json.parent.exists()

    # EAFP recovery should recreate parent directory and persist setting cleanly
    assert service.set_anti_spoiler_enabled(False) is True
    assert nested_json.is_file()
    assert service.is_anti_spoiler_enabled() is False

    data = json.loads(nested_json.read_text(encoding="utf-8"))
    assert data["anti_spoiler"] is False


@pytest.mark.unit
def test_settings_service_detects_external_file_modifications(tmp_path: Path) -> None:
    """Verifies that external modifications to settings.json are detected and merged."""
    custom_json = tmp_path / "external_settings.json"
    service = SettingsService(custom_path=custom_json)
    service.set_anti_spoiler_enabled(False)

    # External program updates settings.json with extra fields
    custom_json.write_text(
        json.dumps({"theme": "solarized", "anti_spoiler": False, "volume": 80}),
        encoding="utf-8",
    )
    # Ensure mtime is strictly different
    new_mtime = custom_json.stat().st_mtime + 2.0
    os.utime(custom_json, (new_mtime, new_mtime))

    # Toggling anti-spoiler preserves the externally added fields
    assert service.toggle_anti_spoiler() is True
    assert service.is_anti_spoiler_enabled() is True

    data = json.loads(custom_json.read_text(encoding="utf-8"))
    assert data["anti_spoiler"] is True
    assert data["theme"] == "solarized"
    assert data["volume"] == 80
