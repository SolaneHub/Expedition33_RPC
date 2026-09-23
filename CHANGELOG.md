# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
