# Clair Obscur: Expedition 33 - Discord Rich Presence

A lightweight, autonomous Windows Discord Rich Presence (RPC) background application designed for *Clair Obscur: Expedition 33*. It resides quietly in the Windows system tray and dynamically synchronizes real-time gameplay status directly to your Discord profile.

---

## Overview & Key Features

- **Continuous Autonomous Detection**: Runs quietly in the background and automatically establishes a Discord Rich Presence connection whenever the game process (`SandFall-Win64-Shipping.exe`) starts, cleanly releasing the session upon game exit.
- **Real-Time Location Tracking**: Automatically reads current zone information from save data and formats official area names directly from the game without artificial translations (e.g., *Versos Draft*, *World Map*, *Forgotten Battlefield*).
- **Live Combat & Enemy Extraction**: Accurately switches between exploration and combat encounters, revealing enemy names and boss titles in real time (e.g., `Fighting: Francois`, `Fighting: Goblu x2` / `In combattimento con: Francois`).
- **Unified Anti-Spoiler Mode**: Dedicated system tray toggle (`Anti-Spoiler Mode [Enabled]`) that simultaneously obscures both active enemy names and location zones into generic placeholders (`Hidden Location`, `In Combat` / `Posizione riservata`, `In combattimento`).
- **Live Session Timer**: Tracks elapsed gameplay duration in the active session.
- **Windows Startup Integration**: Toggle automatic launch on Windows startup directly from the system tray context menu (`HKEY_CURRENT_USER\...\Run`).
- **Minimal System Tray Presence**: Lives discreetly near the taskbar clock with an official stylized "33" golden brush icon and an intuitive context menu.
- **Zero Configuration**: Client ID, icons, and real-time bridge assets are compiled directly into the binary; no manual configuration files required.

---

## Installation & Quick Start

1. Go to the [Releases](https://github.com/SolaneHub/Expedition33_RPC/releases) page and download `Expedition33_RPC.exe`.
2. Run `Expedition33_RPC.exe`. The application minimizes directly to the Windows system tray.
3. Launch *Clair Obscur: Expedition 33*. The status will automatically appear on your Discord profile.

---

## Security, Verification & Antivirus Transparency

All release executables are built automatically in clean runner environments via GitHub Actions.

### Cryptographic Checksums (SHA-256)
Every release includes a `SHA256SUMS.txt` manifest containing checksums for both the executable and the bundled bridge. To verify your downloaded file locally in Windows PowerShell:

```powershell
Get-FileHash .\Expedition33_RPC.exe -Algorithm SHA256
```

Compare the resulting hash with the hash published in `SHA256SUMS.txt` or in the release notes.

### Antivirus & SmartScreen Notes
- **PyInstaller Heuristics**: Standalone executables generated with PyInstaller bundle a Python runtime and compressed binaries. Security software heuristics may occasionally flag unsigned PyInstaller executables as generic false positives.
- **VirusTotal Verification**: Release builds are scanned across 70+ antivirus engines on VirusTotal. Live report links are attached directly to each GitHub Release.
- **Windows SmartScreen**: Because the executable is an open-source binary without an expensive commercial EV certificate, Windows SmartScreen may present a *"Windows protected your PC"* message on first launch. Click **More info** -> **Run anyway**.

---

## Technical Architecture & Combat Bridge

### How It Works

*Clair Obscur: Expedition 33* only flushes save files (`SavesContainer.sav` / `EXPEDITION_0.sav`) to disk during checkpoint saves and map transitions. During active turn-based battles, no files are written to disk.

To provide instant, lag-free combat detection without high CPU polling or memory scanning, the application includes a **lightweight, headless Lua bridge** powered by the community-standard [UE4SS](https://github.com/UE4SS-RE/RE-UE4SS) framework:
- Hooks into the game's battle manager (`AC_jRPG_BattleManager_C`).
- Immediately signals when a fight begins and ends.
- Safely queries enemy names on the Game Thread.
- Disables all debug overlays and hotkeys to preserve a 100% vanilla gameplay experience.

### Automatic Bridge Deployment (Default)

You do not need to manually download or copy mod files:
1. Start `Expedition33_RPC.exe`.
2. The application scans Steam library locations (`libraryfolders.vdf`), detects `.../Expedition 33/Sandfall/Binaries/Win64`, and silently deploys the embedded bridge.
3. You can verify or toggle the bridge at any time by right-clicking the tray icon and viewing `Combat Bridge  [Installed]`.
4. If the game was already running during installation, **restart the game once** so Windows loads the bridge module.

### Manual Bridge Installation (Optional)

If you prefer to inspect or manage files manually:
1. Locate your game's binary folder:
   ```text
   <SteamLibrary>\steamapps\common\Expedition 33\Sandfall\Binaries\Win64\
   ```
2. The bridge consists of:
   - `dwmapi.dll` (standard UE4SS proxy loader)
   - `ue4ss/UE4SS.dll` & `ue4ss/UE4SS-settings.ini`
   - `ue4ss/Mods/mods.txt` (only `Expedition33RPC : 1` enabled)
   - `ue4ss/Mods/Expedition33RPC/scripts/main.lua` (atomic state reporter to `%TEMP%\expedition33_status.json`)

---

## System Tray Controls

Right-clicking the tray icon provides real-time information and persistent toggles:

| Menu Item | Description |
| :--- | :--- |
| `Game: Running / Not running` | Live status and PID of the game process |
| `Location: <Zone Name>` | Current active map/zone (`[Hidden - Anti-Spoiler]` when enabled) |
| `Status: In Combat / Exploring` | Real-time combat state and active enemy target |
| `Discord: Connected / Standby` | Rich Presence IPC connection status |
| `Anti-Spoiler Mode  [Enabled / Disabled]` | Toggles obscuring enemy names and locations across Discord and tray |
| `Combat Bridge  [Installed / Install Now]`| Toggles deployment of the UE4SS combat bridge in Steam binaries |
| `Start with Windows  [X / ]` | Toggles automatic launch on Windows login via registry |
| `Update to vX.X.X  [Install Now]` / `Check for Updates` | Checks for newer releases and applies one-click self-update |
| `Exit` | Disconnects Discord RPC and cleanly shuts down the background process |

---

## Project Structure

```text
├── src/
│   └── expedition33_rpc/
│       ├── __init__.py           # Package initialization & exports
│       ├── __main__.py           # CLI entry point (`python -m expedition33_rpc`)
│       ├── app.py                # Application runtime & single-instance mutex
│       ├── bridge_installer.py   # Steam library detector & automatic bridge deployment
│       ├── detector.py           # Process detector, save parser & zone translator
│       ├── discord_rpc.py        # Discord Rich Presence IPC client (pypresence)
│       ├── settings.py           # Persistent settings & Anti-Spoiler manager (Registry)
│       ├── startup.py            # Windows Registry startup manager (HKCU Run key)
│       ├── tray_app.py           # System tray icon, polling loop & context menu
│       └── assets/               # Embedded application assets
│           ├── icon.ico
│           ├── icon.png
│           └── bridge.zip        # Bundled UE4SS combat bridge package
├── main.py                       # Root execution launcher
├── build_exe.py                  # PyInstaller standalone build script
├── pyproject.toml                # Packaging & tooling configuration (PEP 621, Ruff, Pyright)
├── LICENSE                       # MIT License
├── CHANGELOG.md                  # Project changelog and release history
├── .gitignore                    # Git ignore definitions
└── README.md                     # Project documentation
```

---

## Development & Building

### 1. Prerequisites & Environment
- Python 3.10+
- Package and environment manager: [uv](https://docs.astral.sh/uv/)

### 2. Environment Setup & Dependencies
Using `uv`, virtual environment creation, locking, and dependency installation are handled with a single command:
```bash
uv sync
```

### 3. Code Quality & Linting
```bash
# Linting & Formatting
uv run ruff check --fix
uv run ruff format

# Static Type Checking
uv run pyright
```

### 4. Build Standalone Executable
```bash
uv run python build_exe.py
```
The compiled binary will be placed at `dist/Expedition33_RPC.exe`.

