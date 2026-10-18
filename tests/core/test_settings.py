"""Unit tests for Settings and SettingsService."""

from __future__ import annotations

import json
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
    assert service.target_path == expected_path
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

    assert service.update(anti_spoiler=True, theme="dark") is True
    assert service.anti_spoiler is True

    data = json.loads(custom_path.read_text(encoding="utf-8"))
    assert data["anti_spoiler"] is True
    assert data["theme"] == "dark"

    # Sequential update to an already existing custom key must persist
    assert service.update(theme="light") is True
    data_updated = json.loads(custom_path.read_text(encoding="utf-8"))
    assert data_updated["theme"] == "light"
    assert data_updated["anti_spoiler"] is True


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
        return service.update(anti_spoiler=(i % 2 == 0), **{f"key_{i}": i})

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
        results = list(executor.map(worker, range(20)))

    assert all(results)
    assert custom_path.is_file()
    data = json.loads(custom_path.read_text(encoding="utf-8"))
    for i in range(20):
        assert data[f"key_{i}"] == i
