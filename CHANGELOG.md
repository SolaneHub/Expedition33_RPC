# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [v1.2.0] - 2026-09-24

### Added
- **Enemy Combat Name Extraction**:
  - Real-time extraction of enemy and boss names during turn-based encounters (e.g., `⚔️ Combattendo: Francois`, `⚔️ Battling: Goblu x2`).
  - Resilient multi-tier extraction pipeline querying localized `CharacterName`, `EnemyName`, battle stats components, and cleaned Blueprint actor identifiers.
  - Multi-target grouping with count badges (`x2`, `x3`) and length formatting for Discord Rich Presence.
- **Unified Anti-Spoiler Mode**:
  - Interactive toggle button in the tray context menu (`🛡️ Anti-Spoiler Mode  [✓ Enabled] / [ ]`).
  - Concurrently obscures both enemy names and location zones to prevent story spoilers:
    - Encounters masked to generic `⚔️ In Combattimento` (`⚔️ In Combat`).
    - Locations masked to `📍 Posizione Riservata` (`📍 Hidden Location`).
  - Seamless persistence across restarts via Windows Registry (`HKCU\Software\Expedition33_RPC\AntiSpoiler`).
  - Immediate Rich Presence state synchronization on toggle without restarting the app.

## [v1.1.0] - 2026-09-24

### Added
- **Real-Time Combat Bridge**:
  - Headless, non-intrusive Lua bridge powered by UE4SS interfacing directly with `AC_jRPG_BattleManager_C`.
  - Instant real-time detection of turn-based battle initiation and conclusion without CPU-intensive memory scanning.
  - Silent headless configuration with zero overlays, debug consoles, or gameplay interference.
- **Automatic Bridge Deployment**:
  - Embedded `bridge.zip` bundled directly within the executable.
  - Automatic Steam library discovery (`libraryfolders.vdf`) to detect and deploy into `Sandfall/Binaries/Win64` upon application startup.
  - Context menu toggle in the system tray (`⚔️ Combat Bridge`) for instant verification, installation, or uninstallation.

## [v1.0.0] - 2026-09-23

### Added
- **Autonomous Game Detection**: Automatic detection of *Clair Obscur: Expedition 33* (`SandFall-Win64-Shipping.exe`) process with continuous background polling.
- **Dynamic Discord Rich Presence**:
  - Live zone & location tracking extracted in real time from `SavesContainer.sav`.
  - Automatic game language detection (`GameUserSettings.ini`) and localized area name formatting (e.g., Italian, English).
  - Combat encounter vs. exploration state tracking.
  - Live session duration timer.
  - Autonomous connection management with clean presence release upon game exit.
- **Windows System Tray Application**:
  - Silent notification area presence using an official stylized golden "33" brush icon with transparent alpha.
  - Minimal right-click context menu displaying live game, location, combat, and Discord status.
  - Interactive Windows Startup toggle (`HKEY_CURRENT_USER\Software\Microsoft\Windows\CurrentVersion\Run`).
  - Single-instance mutex protection preventing duplicate processes from running simultaneously.
- **Standalone Distribution**:
  - Embedded Base64 icon fallback and bundled assets for portable distribution via PyInstaller.
  - Self-contained executable requiring no external Python installation or manual setup.
- **Codebase Architecture & Tooling**:
  - Modern Python `src/` layout per PEP 517/518/621.
  - Unified configuration in `pyproject.toml` with `ruff` linter/formatter and `pyright` static type checking.
  - Automated GitHub Actions release workflow for compiling and publishing the standalone Windows executable.
