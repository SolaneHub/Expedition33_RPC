<p align="center">
  <img src="docs/github/official_banner.png" alt="Clair Obscur: Expedition 33 - Discord Rich Presence" width="100%">
</p>

<h1 align="center">Clair Obscur: Expedition 33 — Discord Rich Presence</h1>

<p align="center">
  <strong>An autonomous, lightweight companion bringing real-time dynamic presence for <em>Clair Obscur: Expedition 33</em> directly to your Discord profile.</strong>
</p>

<p align="center">
  <a href="https://github.com/SolaneHub/Expedition33_RPC/releases"><img src="https://img.shields.io/badge/release-v2.3.4-blue.svg" alt="Release"></a>
  <a href="https://www.python.org/"><img src="https://img.shields.io/badge/python-3.12%2B-blue.svg" alt="Python"></a>
  <a href="https://www.microsoft.com/windows"><img src="https://img.shields.io/badge/platform-Windows-lightgrey.svg" alt="Platform"></a>
  <a href="https://github.com/astral-sh/ruff"><img src="https://img.shields.io/badge/code%20style-ruff-000000.svg" alt="Code Style: Ruff"></a>
  <a href="https://github.com/microsoft/pyright"><img src="https://img.shields.io/badge/type%20checked-pyright-green.svg" alt="Type Checked: Pyright"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-MIT%20with%20Attribution-yellow.svg" alt="License: MIT with Attribution"></a>
  <a href="#security"><img src="https://img.shields.io/badge/VirusTotal-Transparent%20Audit-blue.svg?logo=virustotal" alt="VirusTotal: Transparent Audit"></a>
</p>

<p align="center">
  <a href="https://github.com/SolaneHub/Expedition33_RPC/releases/latest/download/Expedition33_RPC.exe">
    <img src="https://img.shields.io/badge/Download-Expedition33__RPC.exe-5865F2?style=for-the-badge&logo=discord&logoColor=white" alt="Download Executable">
  </a>
</p>

<p align="center">
  <a href="#showcase">Showcase</a> •
  <a href="#quick-start">Quick Start</a> •
  <a href="#tray-controls">Tray Controls</a> •
  <a href="#presence-matrix">Presence Matrix</a> •
  <a href="#development">Development</a> •
  <a href="#security">Security</a> •
  <a href="#license">License</a>
</p>

---

<h2 id="showcase">🎬 Showcase</h2>

| Exploration & Combat | Endless Tower | Anti-Spoiler Shield |
| :---: | :---: | :---: |
| ![Exploration & Battle](docs/github/preview_combat.gif?v=2.3.0) | ![Endless Tower](docs/github/preview_tower.gif?v=2.3.0) | ![Anti-Spoiler Shield](docs/github/preview_antispoiler.gif?v=2.3.0) |
| Dynamic transition from exploration (`Spring Meadows`) to battle (`Fighting: Lancelier`). | Transition from entrance exploration (`Endless Tower (Entrance)`) to floor combat (`Stage 1, Trial 1`). | One-click tray shield masking locations (`Hidden Location`) and encounters (`In Combat`). |

---

<h2 id="quick-start">🚀 Quick Start</h2>

1. **Download**: Get the latest [`Expedition33_RPC.exe`](https://github.com/SolaneHub/Expedition33_RPC/releases/latest/download/Expedition33_RPC.exe) from Releases.
2. **Launch**: Double-click `Expedition33_RPC.exe`. It runs in your Windows system tray near the clock.
3. **Play**: Launch *Clair Obscur: Expedition 33* (Steam or PC Game Pass). Discord Rich Presence attaches automatically.

---

<h2 id="tray-controls">🎛️ System Tray Controls</h2>

Right-click the tray icon to monitor status and adjust preferences:

| Menu Item | Live Indicator / Display | Functionality & Action |
| :--- | :--- | :--- |
| **Game Status** | `Game: Running (PID: X)` / `Not running` | Displays real-time process detection status and game PID |
| **Location** | `Location: <Zone Name>` / `[Hidden - Anti-Spoiler]` | Displays current in-game zone or hides it when anti-spoiler mode is active |
| **Status** | `Status: Exploring` / `Combat: Fighting <Enemy>` / `Status: In Combat` / `Status: In Menu` | Shows active exploration or real-time battle encounter targets |
| **Discord** | `Discord: Connected` / `Standby` | Displays local Discord IPC Named Pipe connection status |
| **Anti-Spoiler Mode** | `[Enabled / Disabled]` | One-click toggle masking story locations and enemy encounter titles |
| **Combat Bridge** | `[Installed / Install Now]` | Displays UE4SS Lua bridge status or initiates manual deployment |
| **Start with Windows** | `[X / ]` | Toggles automatic startup registration in `HKCU\...\Run` |
| **Check for Updates** | `Check for Updates` / `Update to vX.X.X` | Checks GitHub Releases API and opens the official release download page in the default web browser |
| **Exit** | *(Action)* | Cleanly disconnects Discord RPC session and closes the companion |

---

<h2 id="presence-matrix">🎮 Presence Matrix</h2>

Presence dynamically updates to reflect current game activity:

| State | Details (Top Line) | State (Bottom Line) | Tooltip | Elapsed Timer |
| :--- | :--- | :--- | :--- | :--- |
| **Exploration** | `Exploring` | `<Zone Name> (<Flag Name>)` *(e.g. `Sirene (Dancing Classes)`)* | `Clair Obscur: Expedition 33` | Active session duration |
| **Combat Encounter** | `Fighting: <Enemy / Boss>` *(e.g. `Fighting: Lancelier`)* | `<Zone Name> (<Flag Name>)` | `Clair Obscur: Expedition 33` | Active session duration |
| **Endless Tower** | `Fighting: <Boss / Enemy>` | `Endless Tower (Stage <X>, Trial <Y>)` | `Clair Obscur: Expedition 33` | Active session duration |
| **Anti-Spoiler Shield** | `In Combat / Exploring` | `Hidden Location` | `Clair Obscur: Expedition 33` | Active session duration |

> [!NOTE]
> Presences automatically adapt to the user's selected game language (supporting all 20 officially localized game languages via `game_data.json`).

---

<h2 id="development">🛠️ Development Guide</h2>

This project uses [`uv`](https://github.com/astral-sh/uv) for dependency management and execution.

```bash
# Sync virtual environment
uv sync

# Lint and format checks
uv run ruff check
uv run ruff format --check

# Static type checking
uv run pyright

# Run test suite
uv run pytest

# Build standalone executable
uv run python build_exe.py
```

Detailed architectural blueprints and system contracts are documented in [ARCHITECTURE.md](ARCHITECTURE.md). For contributor guidelines and agent directives, refer to [AGENTS.md](AGENTS.md).

---

<h2 id="security">🔒 Security & Verification</h2>

Release binaries are built in clean, isolated environments via GitHub Actions. Every release publishes verifiable cryptographic checksums:

| Artifact | SHA-256 (Prefix) | Verification Status | VirusTotal Analysis |
| :--- | :--- | :---: | :---: |
| **`Expedition33_RPC.exe`** | [`fbaaa01b...d9b5`](https://www.virustotal.com/gui/file/fbaaa01ba5bf61d2034ce1b15fed58497674df3f5705b17432a37d10ddc8d9b5) | 🛡️ **Clean** | [Inspect Live Report](https://www.virustotal.com/gui/file/fbaaa01ba5bf61d2034ce1b15fed58497674df3f5705b17432a37d10ddc8d9b5) |
| **`bridge.zip`** | [`3b910cf8...aa1b`](https://www.virustotal.com/gui/file/3b910cf859322d632c2197b7ecd322587f428fac361f19d0ff6224330197aa1b) | 🛡️ **Clean** | [Inspect Live Report](https://www.virustotal.com/gui/file/3b910cf859322d632c2197b7ecd322587f428fac361f19d0ff6224330197aa1b) |

<details>
<summary>📋 <b>Click to view full SHA-256 Checksums</b></summary>

```text
fbaaa01ba5bf61d2034ce1b15fed58497674df3f5705b17432a37d10ddc8d9b5  Expedition33_RPC.exe
3b910cf859322d632c2197b7ecd322587f428fac361f19d0ff6224330197aa1b  bridge.zip
```

</details>

Verify the downloaded binary in PowerShell:
```powershell
Get-FileHash .\Expedition33_RPC.exe -Algorithm SHA256
```

---

<h2 id="license">📜 License</h2>

Licensed under the **[MIT License (with Attribution)](LICENSE)**. See the [LICENSE](LICENSE) file for complete details.

*Clair Obscur: Expedition 33* is a trademark of Sandfall Interactive / Kepler Interactive. This project is an unofficial community companion tool.
