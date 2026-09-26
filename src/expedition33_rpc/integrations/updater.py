import contextlib
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum

from expedition33_rpc import __version__

GITHUB_REPO = "SolaneHub/Expedition33_RPC"
API_LATEST_RELEASE_URL = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
EXE_ASSET_NAME = "Expedition33_RPC.exe"
CHECKSUM_ASSET_NAME = "SHA256SUMS.txt"
USER_AGENT = f"Expedition33-RPC-Updater/{__version__}"


class UpdateState(Enum):
    IDLE = "idle"
    CHECKING = "checking"
    UP_TO_DATE = "up_to_date"
    AVAILABLE = "available"
    DOWNLOADING = "downloading"
    APPLYING = "applying"
    ERROR = "error"


@dataclass
class UpdateInfo:
    tag_name: str
    version_tuple: tuple[int, ...]
    exe_url: str
    exe_size: int
    checksum_url: str | None
    html_url: str


def parse_version(v_str: str) -> tuple[int, ...]:
    """Parses a version string into a comparable tuple of integers.

    Examples:
        'v1.4.0' -> (1, 4, 0)
        '1.4.1' -> (1, 4, 1)
        'v2.0.0-beta.1' -> (2, 0, 0)
    """
    clean = v_str.strip().lstrip("vV")
    numeric_part = clean.split("-")[0]
    nums = []
    for part in numeric_part.split("."):
        try:
            nums.append(int(part))
        except ValueError:
            break
    return tuple(nums) if nums else (0, 0, 0)


def extract_expected_hash(checksum_text: str, filename: str) -> str | None:
    """Extracts SHA-256 hash for a specific file from a standard sha256sums file."""
    target = filename.lower()
    for line in checksum_text.strip().splitlines():
        parts = line.strip().split()
        if len(parts) >= 2:
            file_part = parts[-1].replace("\\", "/").split("/")[-1].lower()
            if file_part == target:
                return parts[0].lower()
    return None


class AppUpdater:
    """Manages background checking, downloading, verifying, and applying application updates."""

    def __init__(
        self,
        current_version: str = __version__,
        on_state_change: Callable[[], None] | None = None,
    ):
        self.current_version = current_version
        self.current_version_tuple = parse_version(current_version)
        self.on_state_change = on_state_change

        self.state = UpdateState.IDLE
        self.available_update: UpdateInfo | None = None
        self.download_progress: int = 0
        self.error_message: str | None = None
        self._lock = threading.Lock()

    def _set_state(
        self,
        new_state: UpdateState,
        error_msg: str | None = None,
        progress: int = 0,
    ):
        with self._lock:
            self.state = new_state
            if error_msg is not None:
                self.error_message = error_msg
            self.download_progress = progress

        if self.on_state_change:
            try:
                self.on_state_change()
            except Exception as e:
                print(f"[Updater] Callback error on state change: {e}")

    def check_for_updates(self) -> UpdateInfo | None:
        """Queries GitHub Releases API for the latest release."""
        self._set_state(UpdateState.CHECKING)
        print(f"[Updater] Checking for updates against {API_LATEST_RELEASE_URL}...")

        try:
            req = urllib.request.Request(
                API_LATEST_RELEASE_URL,
                headers={"User-Agent": USER_AGENT},
            )
            with urllib.request.urlopen(req, timeout=10) as response:
                data = json.loads(response.read().decode("utf-8"))

            tag_name = data.get("tag_name", "")
            remote_tuple = parse_version(tag_name)
            html_url = data.get("html_url", "")

            print(
                f"[Updater] Remote version: {tag_name} ({remote_tuple}) | Current: {self.current_version} ({self.current_version_tuple})"
            )

            if remote_tuple > self.current_version_tuple:
                assets = data.get("assets", [])
                exe_url = None
                exe_size = 0
                checksum_url = None

                for asset in assets:
                    name = asset.get("name", "")
                    if name.lower() == EXE_ASSET_NAME.lower():
                        exe_url = asset.get("browser_download_url")
                        exe_size = asset.get("size", 0)
                    elif name.lower() == CHECKSUM_ASSET_NAME.lower():
                        checksum_url = asset.get("browser_download_url")

                if exe_url:
                    info = UpdateInfo(
                        tag_name=tag_name,
                        version_tuple=remote_tuple,
                        exe_url=exe_url,
                        exe_size=exe_size,
                        checksum_url=checksum_url,
                        html_url=html_url,
                    )
                    with self._lock:
                        self.available_update = info
                    self._set_state(UpdateState.AVAILABLE)
                    print(f"[Updater] Update available: {tag_name}")
                    return info
                else:
                    self._set_state(
                        UpdateState.ERROR,
                        error_msg=f"Release {tag_name} lacks {EXE_ASSET_NAME}",
                    )
                    return None
            else:
                self._set_state(UpdateState.UP_TO_DATE)
                print("[Updater] Application is up to date.")
                return None

        except urllib.error.URLError as e:
            msg = f"Network connection error: {e.reason}"
            print(f"[Updater] {msg}")
            self._set_state(UpdateState.ERROR, error_msg=msg)
            return None
        except Exception as e:
            msg = f"Update check failed: {e}"
            print(f"[Updater] {msg}")
            self._set_state(UpdateState.ERROR, error_msg=msg)
            return None

    def check_in_background(
        self,
        delay_seconds: float = 0.0,
        on_complete: Callable[[UpdateInfo | None], None] | None = None,
    ):
        """Spawns a background thread to check for updates."""

        def _worker():
            if delay_seconds > 0:
                time.sleep(delay_seconds)
            info = self.check_for_updates()
            if on_complete:
                try:
                    on_complete(info)
                except Exception as e:
                    print(f"[Updater] on_complete callback error: {e}")

        t = threading.Thread(target=_worker, daemon=True)
        t.start()

    def download_and_install(
        self,
        on_exit_callback: Callable[[], None] | None = None,
    ) -> bool:
        """Downloads the update, verifies checksum, and applies self-update."""
        with self._lock:
            info = self.available_update

        if not info:
            print("[Updater] No update available to install.")
            return False

        self._set_state(UpdateState.DOWNLOADING, progress=0)

        temp_dir = tempfile.gettempdir()
        temp_exe_path = os.path.join(temp_dir, f"Expedition33_RPC_{info.tag_name}.exe")

        try:
            print(f"[Updater] Downloading update from {info.exe_url} to {temp_exe_path}...")
            req = urllib.request.Request(
                info.exe_url,
                headers={"User-Agent": USER_AGENT},
            )

            hasher = hashlib.sha256()
            downloaded_bytes = 0

            with (
                urllib.request.urlopen(req, timeout=30) as resp,
                open(temp_exe_path, "wb") as out_file,
            ):
                total_bytes = int(resp.headers.get("Content-Length", info.exe_size or 0))

                while True:
                    chunk = resp.read(65536)
                    if not chunk:
                        break
                    out_file.write(chunk)
                    hasher.update(chunk)
                    downloaded_bytes += len(chunk)

                    if total_bytes > 0:
                        pct = int((downloaded_bytes / total_bytes) * 100)
                        self._set_state(UpdateState.DOWNLOADING, progress=pct)

            # Checksum verification if available
            if info.checksum_url:
                print(f"[Updater] Verifying SHA-256 integrity from {info.checksum_url}...")
                try:
                    chk_req = urllib.request.Request(
                        info.checksum_url,
                        headers={"User-Agent": USER_AGENT},
                    )
                    with urllib.request.urlopen(chk_req, timeout=10) as chk_resp:
                        chk_text = chk_resp.read().decode("utf-8")

                    expected_hash = extract_expected_hash(chk_text, EXE_ASSET_NAME)
                    calculated_hash = hasher.hexdigest().lower()

                    if expected_hash:
                        if calculated_hash != expected_hash:
                            raise ValueError(
                                f"Checksum mismatch: expected {expected_hash}, calculated {calculated_hash}"
                            )
                        print(f"[Updater] SHA-256 verification passed: {calculated_hash}")
                    else:
                        print(
                            f"[Updater] Checksum file found, but {EXE_ASSET_NAME} was not listed. Proceeding."
                        )
                except Exception as e:
                    print(f"[Updater] Checksum verification warning: {e}")

            # Transition to applying
            self._set_state(UpdateState.APPLYING)

            is_frozen = getattr(sys, "frozen", False)
            is_windows = sys.platform == "win32"

            if not is_windows or not is_frozen:
                print(
                    f"[Updater] Standalone binary self-update is only supported on Windows executable. Downloaded file preserved at {temp_exe_path}."
                )
                self._set_state(UpdateState.UP_TO_DATE)
                return True

            current_exe = os.path.abspath(sys.executable)
            target_dir = os.path.dirname(current_exe)
            current_pid = os.getpid()
            parent_pid = os.getppid()

            # Create trampoline PowerShell script for 100% hidden and reliable restart
            ps_path = os.path.join(temp_dir, f"e33_updater_{current_pid}.ps1")
            ps_content = f"""# Expedition 33 RPC Silent Auto-Updater
# Strip PyInstaller environment inheritance to prevent _MEIPASS2 collision on restart
Remove-Item env:_MEIPASS2 -ErrorAction SilentlyContinue
Remove-Item env:_MEIPASS -ErrorAction SilentlyContinue
[System.Environment]::SetEnvironmentVariable('_MEIPASS2', $null, 'Process')
[System.Environment]::SetEnvironmentVariable('_MEIPASS', $null, 'Process')

$currentPid = {current_pid}
$parentPid = {parent_pid}
$target = '{current_exe}'
$targetDir = '{target_dir}'
$replacement = '{temp_exe_path}'
$old = '{current_exe}.old'

# 1. Wait for process tree to shut down
Start-Sleep -Seconds 2
Stop-Process -Id $currentPid, $parentPid -Force -ErrorAction SilentlyContinue
Start-Sleep -Seconds 1

# 2. Clean up previous backup if present
if (Test-Path -LiteralPath $old) {{
    Remove-Item -LiteralPath $old -Force -ErrorAction SilentlyContinue
}}

# 3. Move current target binary to .old (with retry loop)
$attempts = 0
while ((Test-Path -LiteralPath $target) -and ($attempts -lt 10)) {{
    try {{
        Move-Item -LiteralPath $target -Destination $old -Force -ErrorAction Stop
        break
    }} catch {{
        $attempts++
        Start-Sleep -Seconds 1
    }}
}}

# 4. Move replacement binary into place (with retry loop)
$attempts = 0
while ($attempts -lt 10) {{
    try {{
        Move-Item -LiteralPath $replacement -Destination $target -Force -ErrorAction Stop
        break
    }} catch {{
        $attempts++
        Start-Sleep -Seconds 1
    }}
}}

# 5. Brief pause to allow Windows Defender to release initial scan lock
Start-Sleep -Seconds 2

# 6. Automatically relaunch the updated application via Windows Shell (clean environment)
$psi = New-Object System.Diagnostics.ProcessStartInfo
$psi.FileName = $target
$psi.WorkingDirectory = $targetDir
$psi.UseShellExecute = $true
[System.Diagnostics.Process]::Start($psi)

# 7. Self-delete this updater script
Remove-Item -LiteralPath $PSCommandPath -Force -ErrorAction SilentlyContinue
"""
            with open(ps_path, "w", encoding="utf-8") as psf:
                psf.write(ps_content)

            # Strip PyInstaller environment variables when spawning updater
            clean_env = os.environ.copy()
            clean_env.pop("_MEIPASS2", None)
            clean_env.pop("_MEIPASS", None)

            print(f"[Updater] Spawning silent updater trampoline script: {ps_path}")
            subprocess.Popen(
                [
                    "powershell.exe",
                    "-NoProfile",
                    "-NonInteractive",
                    "-WindowStyle",
                    "Hidden",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-File",
                    ps_path,
                ],
                creationflags=subprocess.CREATE_NO_WINDOW,
                env=clean_env,
                close_fds=True,
            )

            if on_exit_callback:
                try:
                    on_exit_callback()
                except Exception as e:
                    print(f"[Updater] on_exit_callback error: {e}")

            print("[Updater] Exiting current process for update handover.")
            os._exit(0)

        except Exception as e:
            msg = f"Update failed: {e}"
            print(f"[Updater] {msg}")
            if os.path.exists(temp_exe_path):
                with contextlib.suppress(OSError):
                    os.remove(temp_exe_path)
            self._set_state(UpdateState.ERROR, error_msg=msg)
            return False

    def install_in_background(
        self,
        on_exit_callback: Callable[[], None] | None = None,
    ):
        """Spawns a background thread to download and install the update."""
        t = threading.Thread(
            target=self.download_and_install,
            args=(on_exit_callback,),
            daemon=True,
        )
        t.start()

    def get_status_text(self) -> str:
        """Returns the formatted menu item label based on the current updater state."""
        if self.state == UpdateState.CHECKING:
            return "Checking for Updates..."
        if self.state == UpdateState.DOWNLOADING:
            return f"Downloading Update  [{self.download_progress}%]"
        if self.state == UpdateState.APPLYING:
            return "Restarting Application..."
        if self.state == UpdateState.AVAILABLE and self.available_update:
            return f"Update to {self.available_update.tag_name}  [Install Now]"
        if self.state == UpdateState.UP_TO_DATE:
            return f"Version {self.current_version}  [Up to Date]"
        if self.state == UpdateState.ERROR:
            return "Update Check Failed  [Click to Retry]"
        return "Check for Updates"
