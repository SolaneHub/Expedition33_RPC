import io
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

from scripts import virustotal_scan

from expedition33_rpc.core import settings, startup
from expedition33_rpc.core.app import is_already_running
from expedition33_rpc.core.resources import get_resource_path
from expedition33_rpc.core.settings import (
    is_anti_spoiler_enabled,
    set_anti_spoiler_enabled,
    toggle_anti_spoiler,
)
from expedition33_rpc.core.startup import (
    get_current_executable_command,
    is_startup_enabled,
    set_startup_enabled,
    sync_startup_path,
    toggle_startup,
)
from expedition33_rpc.detection.detector import GameState
from expedition33_rpc.detection.game_data import (
    format_checkpoint_tag,
    format_zone_name,
)
from expedition33_rpc.detection.save_reader import SaveFileReader
from expedition33_rpc.integrations.bridge_installer import (
    find_game_win64_directory,
    install_bridge,
    is_bridge_installed,
    uninstall_bridge,
)
from expedition33_rpc.integrations.discord_rpc import DiscordRPCManager
from expedition33_rpc.integrations.updater import AppUpdater, UpdateInfo, UpdateState


class TestModernizationPackage(unittest.TestCase):
    def test_get_resource_path(self):
        # Existing asset should resolve to a real path
        icon_path = get_resource_path("icon.png")
        self.assertTrue(Path(icon_path).exists(), f"Asset icon.png not found at {icon_path}")
        bridge_path = get_resource_path("bridge.zip")
        self.assertTrue(Path(bridge_path).exists(), f"Asset bridge.zip not found at {bridge_path}")
        # Non-existing file returns filename fallback
        self.assertEqual(get_resource_path("non_existent_file.xyz"), "non_existent_file.xyz")

    def test_get_latest_save_dir(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            reader = SaveFileReader(base_save_dir=tmp_dir)
            # Empty directory returns None
            self.assertIsNone(reader.get_latest_save_dir())

            # Create multiple save subdirectories with different timestamps
            dir1 = Path(tmp_dir) / "Save1"
            dir2 = Path(tmp_dir) / "Save2"
            dir3 = Path(tmp_dir) / "Save3"

            dir1.mkdir()
            time.sleep(0.05)
            dir2.mkdir()
            time.sleep(0.05)
            dir3.mkdir()

            latest = reader.get_latest_save_dir()
            self.assertEqual(latest, str(dir3))

    def test_get_latest_save_dir_non_existent(self):
        reader = SaveFileReader(base_save_dir="/path/does/not/exist")
        self.assertIsNone(reader.get_latest_save_dir())

    def test_get_latest_save_dir_with_stat_oserror(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            reader = SaveFileReader(base_save_dir=tmp_dir)
            good_dir: Any = MagicMock()
            good_dir.is_dir.return_value = True
            good_stat = MagicMock()
            good_stat.st_mtime = 100.0
            good_dir.stat.return_value = good_stat
            good_dir.__str__.return_value = f"{tmp_dir}/GoodDir"

            error_dir: Any = MagicMock()
            error_dir.is_dir.return_value = True
            error_dir.stat.side_effect = OSError("Simulated permission error")

            with patch.object(Path, "iterdir", return_value=[error_dir, good_dir]):
                latest = reader.get_latest_save_dir()
                self.assertEqual(latest, f"{tmp_dir}/GoodDir")

    def test_cross_platform_guards_when_winreg_none(self):
        # Deterministically test non-Windows / missing winreg behavior across all platforms
        with patch.object(settings, "winreg", None):
            set_anti_spoiler_enabled(True)
            self.assertTrue(is_anti_spoiler_enabled())
            set_anti_spoiler_enabled(False)
            self.assertFalse(is_anti_spoiler_enabled())
            toggled = toggle_anti_spoiler()
            self.assertTrue(toggled)
            self.assertTrue(is_anti_spoiler_enabled())
            set_anti_spoiler_enabled(False)

        with patch.object(startup, "winreg", None):
            self.assertFalse(is_startup_enabled())
            self.assertFalse(set_startup_enabled(True))
            sync_startup_path()

        with patch("sys.platform", "darwin"):
            self.assertFalse(is_already_running())

        with patch("sys.platform", "linux"):
            self.assertFalse(is_already_running())

    def test_windows_registry_simulation_for_settings_and_startup(self):
        # Simulate active Windows Registry environment via mocked winreg
        mock_winreg = MagicMock()
        mock_winreg.HKEY_CURRENT_USER = 1
        mock_winreg.KEY_READ = 2
        mock_winreg.KEY_SET_VALUE = 4
        mock_winreg.REG_DWORD = 4
        mock_winreg.REG_SZ = 1

        # Test settings with winreg
        with patch.object(settings, "winreg", mock_winreg):
            # 1. Successful query: anti-spoiler enabled
            mock_key = MagicMock()
            mock_winreg.OpenKey.return_value.__enter__.return_value = mock_key
            mock_winreg.QueryValueEx.return_value = (1, mock_winreg.REG_DWORD)
            self.assertTrue(is_anti_spoiler_enabled())

            # 2. Key not found fallback
            mock_winreg.OpenKey.side_effect = FileNotFoundError("Missing key")
            settings._fallback_anti_spoiler = False
            self.assertFalse(is_anti_spoiler_enabled())
            mock_winreg.OpenKey.side_effect = None

            # 3. Saving setting
            mock_create = MagicMock()
            mock_winreg.CreateKey.return_value.__enter__.return_value = mock_create
            success = set_anti_spoiler_enabled(True)
            self.assertTrue(success)
            mock_winreg.SetValueEx.assert_called_with(
                mock_create, settings.ANTI_SPOILER_VAL, 0, mock_winreg.REG_DWORD, 1
            )

        # Test startup with winreg
        with patch.object(startup, "winreg", mock_winreg):
            # 1. is_startup_enabled with valid existing file
            with tempfile.NamedTemporaryFile() as tf:
                mock_winreg.QueryValueEx.return_value = (f'"{tf.name}"', mock_winreg.REG_SZ)
                mock_winreg.OpenKey.return_value.__enter__.return_value = MagicMock()
                self.assertTrue(is_startup_enabled())

                # 2. is_startup_enabled with missing target file
                mock_winreg.QueryValueEx.return_value = (
                    '"C:\\non_existent_app.exe"',
                    mock_winreg.REG_SZ,
                )
                self.assertFalse(is_startup_enabled())

            # 3. set_startup_enabled(True)
            mock_open = MagicMock()
            mock_winreg.OpenKey.return_value.__enter__.return_value = mock_open
            self.assertTrue(set_startup_enabled(True))
            mock_winreg.SetValueEx.assert_called()

            # 4. set_startup_enabled(False)
            self.assertTrue(set_startup_enabled(False))
            mock_winreg.DeleteValue.assert_called_with(mock_open, startup.APP_NAME)

            # 5. sync_startup_path when mismatched
            mock_winreg.QueryValueEx.return_value = ('"C:\\old_path.exe"', mock_winreg.REG_SZ)
            sync_startup_path()

            # 6. toggle_startup
            mock_winreg.QueryValueEx.return_value = ("", mock_winreg.REG_SZ)
            toggled_state = toggle_startup()
            self.assertTrue(toggled_state)

    def test_startup_command_path_resolution(self):
        cmd = get_current_executable_command()
        self.assertIsInstance(cmd, str)
        self.assertTrue(len(cmd) > 0)
        # Should reference main.py when not frozen
        if not getattr(sys, "frozen", False):
            self.assertIn("main.py", cmd)

    def test_bridge_installer_lifecycle(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            # Initially not installed
            self.assertFalse(is_bridge_installed(tmp_dir))

            # Install real bridge.zip asset
            success, msg = install_bridge(tmp_dir)
            self.assertTrue(success, f"Failed to install bridge: {msg}")
            self.assertTrue(is_bridge_installed(tmp_dir))
            self.assertTrue(os.path.exists(os.path.join(tmp_dir, "dwmapi.dll")))
            self.assertTrue(
                os.path.exists(
                    os.path.join(tmp_dir, "ue4ss", "Mods", "Expedition33RPC", "scripts", "main.lua")
                )
            )

            # Uninstall
            uninstalled, un_msg = uninstall_bridge(tmp_dir)
            self.assertTrue(uninstalled, f"Failed to uninstall bridge: {un_msg}")
            self.assertFalse(is_bridge_installed(tmp_dir))

        # Non-existent target directory
        res, _ = install_bridge("/path/does/not/exist/999")
        self.assertFalse(res)

    def test_find_game_win64_directory_no_game(self):
        with patch.object(startup, "winreg", None):
            res = find_game_win64_directory()
            # In headless CI / non-game environment, should safely return None
            self.assertIsNone(res)

    def test_discord_rpc_manager(self):
        mgr = DiscordRPCManager()
        self.assertFalse(mgr.is_connected)

        # Mock Presence instance
        mock_presence = MagicMock()
        with patch(
            "expedition33_rpc.integrations.discord_rpc.Presence", return_value=mock_presence
        ):
            # Connect
            connected = mgr.connect()
            self.assertTrue(connected)
            self.assertTrue(mgr.is_connected)
            mock_presence.connect.assert_called_once()

            # Second immediate connect should be throttled
            mgr.is_connected = False
            self.assertFalse(mgr.connect())
            mgr.is_connected = True

            # Disconnect
            mgr.disconnect()
            self.assertFalse(mgr.is_connected)
            mock_presence.clear.assert_called()
            mock_presence.close.assert_called()

            # Re-enable connection for update tests
            mgr.rpc = mock_presence
            mgr.is_connected = True

            # 1. Idle state when not running
            idle_state = GameState(is_running=False)
            mgr.update(idle_state)
            self.assertEqual(mgr.last_update_state, "idle")

            # Redundant idle call should not clear again
            mock_presence.clear.reset_mock()
            mgr.update(idle_state)
            mock_presence.clear.assert_not_called()

            # 2. Main menu (Italian)
            menu_it = GameState(
                is_running=True,
                process_pid=1234,
                raw_zone="MainMenu",
                zone_name="Nel menu principale",
                game_language="it",
            )
            mgr.update(menu_it)
            mock_presence.update.assert_called()
            call_kwargs = mock_presence.update.call_args[1]
            self.assertEqual(call_kwargs["details"], "Nel menu principale")
            self.assertEqual(call_kwargs["state"], "Schermata dei titoli")

            # 3. Main menu (English)
            menu_en = GameState(
                is_running=True,
                process_pid=1234,
                raw_zone="MainMenu",
                zone_name="Main Menu",
                game_language="en",
            )
            mgr.update(menu_en)
            call_kwargs = mock_presence.update.call_args[1]
            self.assertEqual(call_kwargs["details"], "In Main Menu")
            self.assertEqual(call_kwargs["state"], "Title Screen")

            # 4. In combat with stage/trial tuple pattern matching (English)
            combat_trial = GameState(
                is_running=True,
                process_pid=1234,
                zone_name="Endless Tower",
                in_combat=True,
                enemy_name="Duollistes",
                tower_stage_trial=(11, 2),
                game_language="en",
            )
            mgr.update(combat_trial)
            call_kwargs = mock_presence.update.call_args[1]
            self.assertEqual(call_kwargs["details"], "Fighting: Duollistes")
            self.assertIn("Endless Tower (Stage 11, Trial 2)", call_kwargs["state"])

            # 5. In combat with stage/trial tuple pattern matching (Italian)
            combat_trial_it = GameState(
                is_running=True,
                process_pid=1234,
                zone_name="Torre Infinita",
                in_combat=True,
                enemy_name="Duollistes",
                tower_stage_trial=(11, 2),
                game_language="it",
            )
            mgr.update(combat_trial_it)
            call_kwargs = mock_presence.update.call_args[1]
            self.assertEqual(call_kwargs["details"], "In combattimento con: Duollistes")
            self.assertIn("Torre Infinita (Fase 11, Prova 2)", call_kwargs["state"])

            # 6. In combat with str super boss pattern matching
            combat_str = GameState(
                is_running=True,
                process_pid=1234,
                zone_name="Endless Tower",
                in_combat=True,
                enemy_name="Simon",
                tower_stage_trial="Simon the Divergent Star",
                game_language="en",
            )
            mgr.update(combat_str)
            call_kwargs = mock_presence.update.call_args[1]
            self.assertIn("(Simon the Divergent Star)", call_kwargs["state"])

            # 7. Exploration with tower_stage_trial pattern matching
            explore_trial = GameState(
                is_running=True,
                process_pid=1234,
                zone_name="Endless Tower",
                in_combat=False,
                tower_stage_trial=(10, 1),
                game_language="en",
            )
            mgr.update(explore_trial)
            call_kwargs = mock_presence.update.call_args[1]
            self.assertEqual(call_kwargs["details"], "Exploring")
            self.assertIn("Endless Tower (Stage 10, Trial 1)", call_kwargs["state"])

            # 8. Anti-spoiler mode hides enemy and location
            combat_spoiler = GameState(
                is_running=True,
                process_pid=1234,
                zone_name="Ancient Sanctuary",
                in_combat=True,
                enemy_name="Secret Boss",
                game_language="en",
            )
            mgr.update(combat_spoiler, anti_spoiler=True)
            call_kwargs = mock_presence.update.call_args[1]
            self.assertEqual(call_kwargs["details"], "In Combat")
            self.assertEqual(call_kwargs["state"], "Hidden Location")

    def test_updater_status_text_match_case(self):
        updater = AppUpdater(current_version="1.5.6")

        updater.state = UpdateState.CHECKING
        self.assertEqual(updater.get_status_text(), "Checking for Updates...")

        updater.state = UpdateState.DOWNLOADING
        updater.download_progress = 42
        self.assertEqual(updater.get_status_text(), "Downloading Update  [42%]")

        updater.state = UpdateState.APPLYING
        self.assertEqual(updater.get_status_text(), "Restarting Application...")

        updater.state = UpdateState.AVAILABLE
        updater.available_update = UpdateInfo(
            tag_name="v1.6.0",
            version_tuple=(1, 6, 0),
            exe_url="https://example.com/e.exe",
            exe_size=100,
            checksum_url=None,
            html_url="https://example.com",
        )
        self.assertEqual(updater.get_status_text(), "Update to v1.6.0  [Install Now]")

        # AVAILABLE state with None available_update should fall back
        updater.available_update = None
        self.assertEqual(updater.get_status_text(), "Check for Updates")

        updater.state = UpdateState.UP_TO_DATE
        self.assertEqual(updater.get_status_text(), "Version 1.5.6  [Up to Date]")

        updater.state = UpdateState.ERROR
        self.assertEqual(updater.get_status_text(), "Update Check Failed  [Click to Retry]")

        updater.state = UpdateState.IDLE
        self.assertEqual(updater.get_status_text(), "Check for Updates")

    def test_game_data_removeprefix(self):
        # format_checkpoint_tag
        res = format_checkpoint_tag(
            "Level.SpawnPoint.AbbestCave.Arena", lang="en", zone="Abbest Cave"
        )
        self.assertEqual(res, "Entrance")

        # format_zone_name removeprefix
        self.assertEqual(format_zone_name("Level_Side_SpringMeadows", lang="en"), "Spring Meadows")
        self.assertEqual(format_zone_name("Level_Main_OldLumiere", lang="en"), "Old Lumiere")

    def test_virustotal_stdout_reconfigure_guard(self):
        # Non-TextIOWrapper stream (e.g. io.StringIO) must not raise AttributeError in main()
        with (
            patch("sys.stdout", io.StringIO()),
            patch("sys.stderr", io.StringIO()),
            patch("sys.argv", ["virustotal_scan.py", "--help"]),
        ):
            with self.assertRaises(SystemExit) as cm:
                virustotal_scan.main()
            self.assertEqual(cm.exception.code, 0)


if __name__ == "__main__":
    unittest.main()
