# Developer & AI Agent Guidelines: Expedition33_RPC

This document outlines the architecture, developer workflows, conventions, and data formats for `expedition33-discord-rpc`.

---

## 1. Quick Commands

All tasks are managed with [`uv`](https://github.com/astral-sh/uv).

| Task | Command |
| :--- | :--- |
| **Sync dependencies** | `uv sync` |
| **Run unit tests (fast)** | `uv run pytest -m unit` |
| **Run integration tests** | `uv run pytest -m integration` |
| **Run all tests** | `uv run pytest` |
| **Lint code** | `uv run ruff check` |
| **Check formatting** | `uv run ruff format --check` |
| **Auto-format code** | `uv run ruff format` |
| **Type check** | `uv run pyright` |
| **Run application** | `uv run python main.py` |
| **Build executable** | `uv run python build_exe.py` |


---

## 2. Architecture & Modules

The repository follows a clean, modular structure under `src/expedition33_rpc/`:

```text
src/expedition33_rpc/
├── core/                   # Application lifecycle and core utilities
│   ├── app.py              # Single instance mutex/file lock and app entrypoint
│   ├── orchestrator.py     # Headless AppOrchestrator coordinator with facade and pub/sub
│   ├── settings.py         # Persistent JSON configuration with legacy registry migration
│   ├── startup.py          # Windows autostart (Run registry key) management
│   └── resources.py        # Bundled asset path resolution (PyInstaller _MEIPASS)
├── detection/              # Game state detection and telemetry pipelines
│   ├── compat_paths.py     # Cross-platform IPC paths (Windows, Linux, Steam Deck Proton)
│   ├── detector.py         # GameDetector coordinating telemetry providers and immutable GameState
│   ├── normalization.py    # Pure domain string normalization and location formatting
│   ├── game_data.py        # Lazy name dictionaries (EN/IT), regexes, Endless Tower trial matcher
│   └── timer_tracker.py    # ZoneTimerTracker state machine for smooth Discord presence times
├── integrations/           # External service integrations
│   ├── bridge_installer.py # Automatic and manual UE4SS Lua bridge installation
│   ├── discord_rpc.py      # Native lightweight Discord IPC wire client with rate-limiting
│   └── updater.py          # GitHub Releases auto-update checker and background worker
└── ui/                     # Presentation and UI layer
    ├── presentation.py     # Pure presentation formatting logic for Discord and Tray
    └── tray_app.py         # Win32 system tray application powered by pystray
```

### Key Architectural Concepts
1. **Dynamic IPC Telemetry Pipeline (`detection/detector.py`)**:
   - `BridgeStateProvider`: Real-time telemetry provider reading memory/IPC JSON from the UE4SS Lua mod.
   - Enforces a 5.0-second wall-clock freshness timeout to immediately expire stale combat or zone telemetry when the game or mod halts.
2. **Dependency Injection**:
   - `GameDetector` accepts injected `providers`, `timer_tracker`, and `process_scanner` for deterministic unit testing.
3. **Pure Presentation Layer (`ui/presentation.py`)**:
   - Extracts string formatting away from Discord IPC and GUI event loops, preventing divergent texts and enabling fast unit testing without mocks.
4. **Mirrored Test Suite Architecture (`tests/`)**:
   - Follows clean layering mirroring `src/` (`core/`, `detection/`, `integrations/`, `ui/`, `e2e/`, `harness/`).
   - Shared mock utilities and binary fixtures are consolidated in `tests/harness/`.

---

## 3. Development Conventions

- **Language Level**: Python 3.12+.
  - Use PEP 695 type alias syntax (`type MyAlias = ...`).
  - Use `typing.override` for inherited methods.
  - Use standard library types for generics (`list[str]`, `dict[str, Any]`, `tuple[int, int] | None`).
  - Use structural pattern matching (`match ... case`) where appropriate.
- **Typing**: Pyright is configured in `pyproject.toml` with `typeCheckingMode = "standard"`. All new code must be fully typed and pass `uv run pyright` without errors.
- **Formatting & Linting**: Ruff is the standard linter and formatter. Line length is 100 characters. Run `uv run ruff check` and `uv run ruff format --check` before committing.
- **Cross-Platform Compatibility**: While the app targets Windows, scripts and test suites must run cross-platform (macOS, Linux, Windows). Use `os.pathsep`, `Path`, and conditional guards for Windows registry (`winreg`).

---

## 4. Telemetry & Data Formats

### 4.1. UE4SS Lua Bridge Telemetry IPC Format

Bridge Mod writes state to `%TEMP%\expedition33_status.json` or `%LOCALAPPDATA%\Sandfall\rpc_status.json`:

```json
{
  "timestamp": 1727788800.0,
  "zone": "Level_Main_OldLumiere",
  "in_combat": true,
  "enemy_name": "Duollistes",
  "floor": null,
  "checkpoint": "Entrance"
}
```

### 4.2. VirusTotal Summary Report (`virustotal_report.json`)

Written by `.github/scripts/virustotal_scan.py` during builds or CI:

```json
{
  "generated_at": 1727788800.0,
  "files": {
    "Expedition33_RPC.exe": {
      "sha256": "098718d1e4ebb5a3c7d9bf3ea86d0dd3474145b7cbde52fe95e5ddb6b635110f",
      "status": "COMPLETED",
      "positives": 0,
      "total": 72,
      "permalink": "https://www.virustotal.com/gui/file/098718d1e4ebb5a3c7d9bf3ea86d0dd3474145b7cbde52fe95e5ddb6b635110f"
    }
  }
}
```
