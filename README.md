# Clair Obscur: Expedition 33 - Discord Rich Presence

A lightweight, autonomous Windows Discord Rich Presence (RPC) application designed for *Clair Obscur: Expedition 33*. It resides quietly in the Windows system tray and dynamically synchronizes real-time gameplay status directly to your Discord profile.

---

## Features

- 🎮 **Continuous Autonomous Detection**: Runs quietly in the background and automatically establishes a Discord Rich Presence connection whenever the game process (`SandFall-Win64-Shipping.exe`) starts, cleanly releasing the session upon game exit.
- 📍 **Real-Time Location Tracking**: Automatically reads current zone information from save data and translates area names to match your game's active language setting (e.g., *Vero Cugino di Esquie*, *Verso's Draft*, *World Map*).
- ⚔️ **Combat & Exploration Status**: Accurately indicates whether you are currently in battle or exploring the world.
- ⏱️ **Live Session Timer**: Tracks elapsed gameplay duration in the current session.
- 🚀 **Windows Startup Integration**: Toggle automatic launch on Windows startup directly from the system tray context menu (`HKEY_CURRENT_USER\...\Run`).
- 🔕 **Minimal System Tray Presence**: Lives discreetly near the Windows taskbar clock with an official stylized "33" golden brush icon and an intuitive right-click context menu.
- 📦 **Zero External Setup & Embedded Assets**: Client ID and visual assets are compiled directly into the binary; no manual configuration files required.

---

## Project Structure

```text
├── src/
│   └── expedition33_rpc/
│       ├── __init__.py      # Package initialization & exports
│       ├── __main__.py      # CLI entry point (`python -m expedition33_rpc`)
│       ├── app.py           # Application runtime & single-instance mutex
│       ├── detector.py      # Process detector, save parser & zone translator
│       ├── discord_rpc.py   # Discord Rich Presence IPC client (pypresence)
│       ├── startup.py       # Windows Registry startup manager (HKCU Run key)
│       ├── tray_app.py      # System tray icon, polling loop & context menu
│       └── assets/          # Embedded application icons
│           ├── icon.ico
│           └── icon.png
├── main.py                  # Root execution launcher
├── build_exe.py             # PyInstaller standalone build script
├── pyproject.toml           # Unified packaging configuration (PEP 621, Ruff, Pyright)
├── LICENSE                  # MIT License
├── CHANGELOG.md             # Project changelog and release history
├── .gitignore               # Git ignore definitions
└── README.md                # Project documentation
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
