# Clair Obscur: Expedition 33 - Discord Rich Presence

A lightweight, autonomous Windows Discord Rich Presence (RPC) application designed for *Clair Obscur: Expedition 33*. It resides quietly in the Windows system tray and dynamically synchronizes real-time gameplay status directly to your Discord profile.

---

## Features

- 🎮 **Continuous Autonomous Detection**: Runs quietly in the background and automatically establishes a Discord Rich Presence connection whenever the game process (`SandFall-Win64-Shipping.exe`) starts, cleanly releasing the session upon game exit.
- 📍 **Real-Time Location Tracking**: Automatically reads current zone information from save data and translates area names to match your game's active language setting (e.g., *Vero Cugino di Esquie*, *Verso's Draft*, *World Map*).
- ⚔️ **Live Combat & Enemy Extraction**: Accurately switches between exploration and combat encounters, revealing enemy names and boss titles in real time (e.g., `⚔️ Combattendo: Francois`, `⚔️ Battling: Goblu x2`).
- 🛡️ **Unified Anti-Spoiler Mode**: Dedicated system tray toggle (`🛡️ Anti-Spoiler Mode [✓]`) that simultaneously obscures both active enemy names and location zones into generic place-holders (`📍 Posizione Riservata`, `⚔️ In Combattimento`).
- ⏱️ **Live Session Timer**: Tracks elapsed gameplay duration in the current session.
- 🚀 **Windows Startup Integration**: Toggle automatic launch on Windows startup directly from the system tray context menu (`HKEY_CURRENT_USER\...\Run`).
- 🔕 **Minimal System Tray Presence**: Lives discreetly near the Windows taskbar clock with an official stylized "33" golden brush icon and an intuitive right-click context menu.
- 📦 **Self-Contained & Zero Configuration**: Client ID, icons, and real-time bridge assets are compiled directly into the binary; no manual configuration files required.

---

## Real-Time Combat Bridge

### How It Works

*Clair Obscur: Expedition 33* only flushes save files (`SavesContainer.sav` / `EXPEDITION_0.sav`) to disk during checkpoint saves and map transitions. During active turn-based battles, no files are written to disk.

To provide instant, lag-free combat detection without high CPU polling or memory scanning, the application includes a **lightweight, headless Lua bridge** powered by the community-standard [UE4SS](https://github.com/UE4SS-RE/RE-UE4SS) framework:
- It hooks into the game's battle manager (`AC_jRPG_BattleManager_C`).
- When a fight begins, it immediately signals the battle state.
- When all enemies are defeated or the battle ends, it instantly returns to exploration mode.
- All debug consoles, overlays, and hotkeys are completely disabled to keep your gameplay 100% clean and vanilla.

### Automatic Installation (Default)

You do **not** need to manually download or copy any mod files:
1. Start `Expedition33_RPC.exe`.
2. The executable automatically searches your Steam libraries, locates the game's executable directory (`.../Expedition 33/Sandfall/Binaries/Win64`), and silently deploys the embedded bridge.
3. You can verify or toggle the bridge at any time by right-clicking the tray icon and viewing `⚔️ Combat Bridge  [✓ Installed]`.
4. If the game was already running during installation, simply **restart the game once** so Windows loads the bridge module on startup.

### Manual Installation (Optional)

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
├── pyproject.toml                # Unified packaging configuration (PEP 621, Ruff, Pyright)
├── LICENSE                       # MIT License
├── CHANGELOG.md                  # Project changelog and release history
├── .gitignore                    # Git ignore definitions
└── README.md                     # Project documentation
```

---

## Development & Code Quality

### 1. Install Development Dependencies
```bash
pip install -e .[dev]
```

### 2. Linting and Formatting with Ruff
```bash
# Run linter and apply automatic fixes
ruff check --fix

# Format source files
ruff format
```

### 3. Type Checking with Pyright
```bash
pyright
```

### 4. Build Standalone Executable
```bash
python build_exe.py
```
The compiled binary will be placed at `dist/Expedition33_RPC.exe`.
