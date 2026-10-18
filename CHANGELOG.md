# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [v2.0.5] - 2026-10-18

### Fixed
- **Discord Wire Protocol 128 UTF-8 Bytes Boundary Clamping (`ui.presentation`)**:
  - Fixed `truncate_presence_field` to strictly clamp at the 128 **byte** UTF-8 wire protocol limit instead of character count.
  - Implemented safe byte-boundary decoding with `errors="ignore"`, preventing packet rejections and IPC socket crashes when displaying multibyte languages (Chinese, Russian, Japanese, Korean, Arabic, emojis).
  - Added dedicated test coverage in `tests/ui/test_presentation.py`.

### Changed & Optimized
- **Non-blocking Asynchronous Lua Bridge Auto-Installation (`core.orchestrator`)**:
  - Offloaded `bridge.zip` unzipping and filesystem modifications to a background daemon thread with guard flags and a 30s cooldown.
  - Eliminated telemetry polling loop jitter (0.5–2s freeze) and Discord socket heartbeat timeouts on game launch.
- **Clean Event Subscription Pattern (`core.orchestrator`, `ui.tray_app`)**:
  - Replaced runtime monkey-patching of `orchestrator.on_update_available` with formal `subscribe_update_available()` observer pattern returning an idempotent unsubscribe callback.
- **Simplified Settings Persistence Architecture (`core.settings`)**:
  - Replaced complex locking and nanosecond temp files with a streamlined typed `Settings` dataclass and atomic `.replace()` operations, with in-memory rollback on filesystem errors.

## [v2.0.4] - 2026-10-18

### Added
- **Persistent Checkpoint Save Reader Fallback (`detection.save_reader`)**:
  - Restored and modernized `SaveFileReader` (Python 3.12+, zero external dependencies) to dynamically read the active player save (`EXPEDITION_*.sav`).
  - Extracts `LastUsedSavePoint` and validates semantic zone matching, restoring checkpoint presence display in parentheses (e.g. `Verso's Drafts (Candy Land)`) even when the in-game save menu is closed.
  - Implemented cached binary inspection with filesystem `mtime` checking for zero overhead.

### Fixed
- **Eliminated Engine Game Thread Freezes & Micro-Stutters**:
  - Fixed severe periodic stutter (0.5–1.0s every 4 seconds) caused by UE4SS Lua bridge debug routines iterating `FindAllOf("UserWidget")` across 100,000+ UObjects and all streaming levels on the engine Game Thread.
  - Streamlined `main.lua` to O(1) level identification via `UGameplayStatics::GetCurrentLevelName()`, eliminating all level iteration and blocking disk I/O.
  - Updated bundled `src/expedition33_rpc/assets/bridge.zip`.

## [v2.0.3] - 2026-10-14

### Fixed
- **Settings Persistence Optimization & Responsiveness**:
  - Implemented thread-safe in-memory caching and reentrant locking (`RLock`) in `SettingsService`, eliminating redundant disk reads during setting queries and toggles.
  - Adopted direct binary stream write with EAFP parent directory recreation, cutting hot-path UI toggle latency from ~12.6ms down to ~0.26ms.
  - Hardened multi-process temporary filename generation with `os.getpid()`, unique thread IDs, and high-precision timestamps to prevent collisions.
  - Added filesystem modification timestamp (`st_mtime`) tracking to automatically detect and merge external configuration file changes.
  - Suppressed debug standard output in tray menu actions to avoid terminal I/O latency regressions in headless test runners.

## [v2.0.2] - 2026-10-14

### Changed
- **Optimized Lazy Telemetry Catalog Loading**:
  - Guarded `game_data.__getattr__` with strict `_LAZY_ATTRIBUTES` whitelist before reading JSON catalogs, preventing premature 1.26MB file reads during Python module inspection.
  - Eliminated top-level catalog imports from `normalization.py` and `presentation.py` in favor of deferred module-attribute access.
- **Franciscan Architectural Refactoring & Pruning**:
  - Extracted smoke test logic from `core/app.py` into dedicated `core/smoke.py` and registered PyInstaller hidden import.
  - Pruned unused ghost hash maps, redundant sentinels (`_UnsetType`), duplicate parameters, and unused platform lock wrappers.
  - Streamlined `AppOrchestrator` state change subscriber dispatching to ensure decoupled and concurrent multi-listener delivery.

### Fixed
- **Process Lifecycle & Steam AppID Compatibility**:
  - Decoupled process lifecycle validation from strict AppID dependency, preventing false disconnects on alternative distribution paths.
  - Hardened bridge provider injection in `GameDetector` to allow deterministic opt-out via `bridge_provider=None` using sentinel defaults.

## [v2.0.1] - 2026-10-14

### Fixed
- **Folder Selection Dialog Lifecycle & Process Isolation**:
  - Isolated folder selection (`_prompt_folder_selection`) into a dedicated worker thread with its own clean Single-Threaded Apartment (STA) and Win32 message pump, eliminating deadlocks with `pystray`'s system tray window message loop.
  - Bound native directory dialogs explicitly to the Tk root window (`parent=root`), ensuring proper window ownership hierarchy under Windows DWM.
  - Implemented guaranteed cleanup in `finally:` blocks with `root.attributes("-topmost", False)`, `root.update_idletasks()`, `root.update()`, and `root.destroy()`, ensuring the dialog window closes and disappears immediately upon clicking Cancel or the window close (`X`) button without leaving frozen ghost windows.
  - Added comprehensive lifecycle and cancellation unit tests for folder selection.

## [v2.0.0] - 2026-10-14

### Added
- **Decoupled Presence Engine (`core.presence`)**:
  - Introduced immutable `PresencePayload` Data Transfer Object (DTO) encapsulating all Discord rich presence state fields (`state`, `details`, `large_image`, `large_text`, `small_image`, `small_text`, `start_timestamp`, `pid`).
  - Completely decoupled `DiscordRPCManager` from the UI layer (`ExpeditionTrayApp`) and domain models: the presence client exclusively consumes `PresencePayload`, enabling pure headless operation and isolated unit testing.
- **Native Platform Abstraction Layer (`core.platform`)**:
  - Consolidated all operating system interactions into a unified platform module (`core.platform`):
    - `PlatformMutex`: Named Win32 Mutex on Windows with automatic POSIX advisory file lock (`fcntl.flock`) fallback on Linux/macOS.
    - `FileLock`: Robust cross-platform non-blocking file locking for atomic configuration updates.
    - `PlatformRegistry`: Safe abstraction over Windows Registry (`winreg`) with no-op fallbacks for POSIX platforms.
  - Completely eliminated direct low-level Win32 ctypes and winreg imports from application business logic.
- **Interactive Telemetry Simulation Harness (`tools/simulate_telemetry.py`)**:
  - Added standalone developer CLI tool for simulating game lifecycles, combat transitions, Endless Tower trials, and location changes in real-time or automated batch mode.
  - Added automated simulation regression tests (`tests/detection/test_simulate_telemetry.py` and `tests/e2e/test_process_lifecycle.py`), expanding test suite to 175 automated tests.

### Changed
- **Zero Static Type Suppressions & 100% Pyright Strict Safety**:
  - Eradicated all 12 static type suppressions (`type: ignore`) across production and test code.
  - Full codebase strict type compliance validated under Python 3.12+ and Pyright with 0 errors and 0 warnings.
- **Detection Kernel Purification & LRU Caching**:
  - Standardized domain combat and exploration states around canonical `Exploring` domain tokens.
  - Replaced complex lazy data structures with standard Python `functools.lru_cache` and direct protocol bindings (`BridgeProviderProtocol`).
  - Implemented adaptive idle polling in detector to minimize background CPU usage when the game is not running.
- **Package Entrypoint Lazy Exports**:
  - Modernized `src/expedition33_rpc/__init__.py` with PEP 562 module-level `__getattr__` and `__dir__`, ensuring fast startup times by deferring heavyweight imports until accessed.

## [v1.9.0] - 2026-10-13

### Added
- **Universal 20-Language Localization**:
  - Extracted and normalized official in-game strings across all 20 officially supported languages directly from Unreal Engine `.locres` binary catalogs: English (`en`), Italian (`it`), French (`fr`), German (`de`), Spanish (`es`), Latin American Spanish (`es-419`), Japanese (`ja`), Korean (`ko`), Polish (`pl`), Brazilian Portuguese (`pt-BR`), Russian (`ru`), Simplified Chinese (`zh-Hans`), Traditional Chinese (`zh-Hant`), and more.
  - Guaranteed 100% key symmetry across all 765 checkpoint tags and 48 exploration zones in all 20 languages.
  - Fully mapped all 33 Endless Tower stages and trials from game data table `ST_BattleTowerStages` with localized stage and trial titles across all languages.
  - Localized Discord Rich Presence details and state presentation templates across all 20 languages.
- **SSOT Asset Catalog Architecture & Code Style Standards**:
  - Consolidated presentation templates, localized strings, and domain dictionaries into `src/expedition33_rpc/assets/game_data.json` as the Single Source of Truth (SSOT).
  - Integrated Prettier formatting (`.prettierrc.json`, `.prettierignore`) and added automated Prettier validation in GitHub Actions CI.
- **Concurrency & IPC Hardening (`FILE_SHARE_DELETE`)**:
  - Enforced Win32 `FILE_SHARE_DELETE` sharing flags on Windows file handles when reading bridge telemetry files, eliminating race condition locks during concurrent file writes by the game's Lua thread.
- **Lua Bridge Integrity & Syntax Validation**:
  - Embedded updated authentic UI token names inside the bundled `bridge.zip` asset.
  - Added automated Lua tokenizer and AST syntax validator harness (`tests/harness/lua_validator.py`) to prevent bridge script regressions during build time.

### Changed
- **Dependency Injection & Callback Modernization**:
  - Completed explicit Protocol-based Dependency Injection across `AppOrchestrator`, `GameDetector`, and UI layers.
  - Streamlined orchestrator communication from generic multi-consumer pub/sub buses to direct, typed 1-to-1 event callbacks.
  - Expanded automated test suite to 148 unit, integration, and E2E tests.

## [v1.8.0] - 2026-10-12

### Added
- **Multi-Target Process Unification (Steam & Game Pass WinGDK)**:
  - Added seamless simultaneous detection support for both Steam (`SandFall-Win64-Shipping.exe`) and PC Game Pass / Microsoft Store (`SandFall-WinGDK-Shipping.exe`) game editions.
  - Unified detection target configuration to `target_process_names` with dynamic process image resolution.
- **Immutable Process Context (`GameProcessInfo`)**:
  - Encapsulated PID, executable name, and resolved binary paths within immutable `GameProcessInfo` and `GameState` domain structures.
  - Bound Discord Rich Presence directly to the detected executable PID for both Steam and WinGDK targets, guaranteeing accurate Discord activity association.
- **Discord IPC Protocol Framing (`DiscordFrameCodec`)**:
  - Extracted binary length-prefix framing and JSON payload encoding into dedicated, unit-tested `DiscordFrameCodec`, eliminating nested wrapper abstractions.
- **Structural Protocol Typing**:
  - Introduced clean `typing.Protocol` definitions for `ProcessLike`, `BridgeInstallerProtocol`, and `StartupProtocol`.
- **Precompiled Hash Lookup Acceleration**:
  - Optimized checkpoint tag lookups using precompiled $O(1)$ dictionary lookups instead of repetitive regular expression scans.

### Changed
- **Ultra-Fast Test Suite Execution**:
  - Accelerated full test suite runtimes to under 2.2 seconds by replacing wall-clock sleep loops with deterministic iterations, lowering test HTTP server polling intervals to 0.01s, and injecting virtual `time_provider` clocks into telemetry providers.
- **Facade Encapsulation in AppOrchestrator**:
  - Replaced ceremonial wrapper services with clean atomic facade methods (`install_bridge_to`, `subscribe_update_available`).
  - Added thread-safe state synchronization and re-entrant update subscription handling.

### Fixed
- **PyInstaller Bundled UI Smoke Test in CI**:
  - Hardened GitHub Actions release workflow with automated headless smoke testing of PyInstaller executable binaries, ensuring correct bundling of Tkinter, PIL, pystray, and platform dependencies.

## [v1.7.0] - 2026-10-11

### Added
- **Headless Application Orchestrator (`core.orchestrator`)**:
  - Introduced `AppOrchestrator` central coordinator to decouple lifecycle management, state polling, and external service interactions from GUI event loops.
  - Added thread-safe pub/sub notification mechanisms and lifecycle synchronization (`start()`, `stop()`, `tick()`).
  - Added exponential backoff retry mechanism for automatic UE4SS bridge deployment upon detection failures.
- **Pure Presentation Formatting Layer (`ui.presentation`)**:
  - Extracted string formatting, combat details, and presence string assembly into pure, stateless functions (`format_discord_presence`, `format_location_name`, `format_tray_status`), preventing divergent UI/Discord text and allowing 100% test coverage without UI mocks.
- **Pure Domain String Normalization (`detection.normalization`)**:
  - Isolated clean string sanitization, token stripping, and checkpoint parsing from low-level I/O.
- **Cross-Platform Compatibility Paths (`detection.compat_paths`)**:
  - Added Linux and Steam Deck Proton/Wine prefix resolution alongside native Windows paths, ensuring smooth telemetry file discovery across varied operating environments.
- **Comprehensive Mirrored Test Suite & Test Harness**:
  - Re-architected test suite to mirror `src/` modular layout across `tests/core/`, `tests/detection/`, `tests/integrations/`, `tests/ui/`, `tests/e2e/`, and `tests/harness/`.
  - Added mock Discord IPC pipe transport, in-process HTTP updater test server, and multi-threaded IPC concurrency stress tests, reaching 114 automated tests.
  - Added GitHub Actions CI workflow (`.github/workflows/ci.yml`) validating multi-platform test passes, linting, formatting, and type checks.

### Changed
- **Pure Real-Time Telemetry Pipeline**:
  - Bound `GameDetector` directly to `BridgeStateProvider` consuming telemetry from the UE4SS Lua bridge with an enforced 5.0-second freshness window.
  - Eliminated stale combat states and lingering zone information through strict timestamp validation.
- **Native Lightweight Discord IPC Client (`integrations.discord_rpc`)**:
  - Replaced external third-party client wrappers with an in-house asynchronous wire client featuring automatic rate-limiting, thread-safe cache invalidation (`invalidate()`), and resilient reconnection logic.
- **Atomic Configuration Management (`core.settings`)**:
  - Migrated configuration persistence from the Windows Registry to thread-safe, atomic JSON storage (`%APPDATA%/Expedition33_RPC/settings.json`) with automatic backward-compatible migration of legacy registry keys.
- **Centralized Asset Catalog (`assets/game_data.json`)**:
  - Externalized static game data dictionaries, trial mappings, and regex definitions into a standalone JSON asset catalog loaded lazily.

### Removed
- **Legacy Binary Save File Parsing**:
  - Completely purged `detection.save_reader`, save-file binary decoders, and associated static test fixtures, reducing binary footprint and eliminating disk I/O contention with the game engine.

## [v1.6.0] - 2026-10-06

### Changed
- **Python 3.12 Runtime & Toolchain Modernization**:
  - Upgraded target Python version requirement to `>=3.12` (`.python-version` pinned to `3.12`, Pyright and Ruff configured for `py312`).
  - Adopted PEP 695 native type parameter and type alias syntax (`type TowerTrial = tuple[int, int] | str`, `type RawGameData = dict[str, Any]`, `type UpdateCallback`, `type ExitCallback`).
  - Adopted PEP 698 `@override` decorator in polymorphic telemetry providers (`BridgeStateProvider`, `SaveFileStateProvider`).
  - Modernized `updater.py`, `discord_rpc.py`, and `tray_app.py` with Python 3.12 structural pattern matching (`match/case`) for game trials, combat encounters, and updater states.
  - Replaced manual chunked loops and full-binary memory reads with Python 3.12 native streaming `hashlib.file_digest` in `scripts/virustotal_scan.py` and GitHub Actions release workflow.
  - Normalized package versioning in `pyproject.toml` to PEP 440 (`1.6.0`).
  - Extended Pyright static type checking coverage across `src/`, `scripts/`, `tests/`, `main.py`, and `build_exe.py` with zero errors.

### Fixed
- **Cross-Platform Test Execution & Windows Registry Fallbacks**:
  - Implemented graceful `ImportError` fallbacks for `winreg` across `core.settings`, `core.startup`, and `integrations.bridge_installer`, enabling the test suite (`unittest discover tests`) to run deterministically on non-Windows platforms (macOS/Linux) and CI environments without failing on missing Win32 APIs.
  - Corrected Windows autostart path resolution in `core.startup` to accurately target root `main.py` via 4-level directory traversal (`Path(__file__).resolve().parents[3] / "main.py"`).
  - Added platform guard in `core.app` single-instance check to prevent `ctypes.windll` errors on non-Windows hosts.
  - Hardened save directory discovery in `detection.save_reader` (`get_latest_save_dir`) with $O(N)$ `Path.iterdir()` and per-item `OSError` resilience during concurrent folder changes.

### Refactored
- **Asset Resolution Centralization**:
  - Extracted shared PyInstaller and development resource locator `get_resource_path()` into dedicated module `core.resources`, eliminating code duplication between `bridge_installer.py` and `tray_app.py`.
- **String Handling Modernization**:
  - Replaced legacy string replacement logic with `str.removeprefix()` in `detection.game_data` and `detection.save_reader`.

### Added
- **Modernization & Cross-Platform Test Suite (`tests/test_modernization.py`)**:
  - Added 13 comprehensive unit tests validating resource resolution, save reader resilience, Windows Registry simulation, bridge lifecycle, Discord RPC trial formatting, and VirusTotal stdout safety, expanding test coverage to 25 automated tests.
  - Added pre-build automated test verification step (`uv run python -m unittest discover tests`) to GitHub Actions release workflow.

## [v1.5.6] - 2026-09-29

### Changed
- **High-Performance VirusTotal CI Scanning Pipeline**:
  - Replaced legacy blocking `ghaction-virustotal` action with a lightweight, native Python scanner ([`scripts/virustotal_scan.py`](scripts/virustotal_scan.py)) with zero external dependencies.
  - Added deterministic SHA-256 cache verification via `GET /api/v3/files/{sha256}` to eliminate redundant uploads of unchanged assets (such as `bridge.zip`).
  - Added non-blocking direct release publishing with permanent VirusTotal permalinks, cutting CI release workflow execution time from minutes down to seconds.
  - Implemented strict rate-limiting compliance (4 req/min) with automatic backoff and retry on HTTP 429 (`Retry-After`).
  - Added automated large-file upload endpoint negotiation for binaries exceeding 32 MB.
  - Embedded real-time detection ratio metrics directly into GitHub Release notes and workflow summaries (`dist/virustotal_report.json`).
- **VirusTotal Transparency & Documentation Layout**:
  - Updated live VirusTotal audit permalinks and cryptographic SHA-256 hashes in `README.md` for `Expedition33_RPC.exe` (65/71 clean; transparent technical breakdown of all 6 heuristic/cloud ML flags: Microsoft `Wacatac.B!ml`, SentinelOne `Static AI - Suspicious PE`, Elastic `Malicious (high Confidence)`, Bkav Pro `W32.Malware.15AC2E30`, SecureAge `Malicious`, and Arctic Wolf `Unsafe`) and `bridge.zip` (63/64 clean).
  - Re-architected the Live VirusTotal Analysis Reports table with a responsive layout and compact hash previews, eliminating horizontal table overflow across standard screen widths.
  - Added an expandable `<details>` section providing one-click copyable full SHA-256 checksums matching `dist/SHA256SUMS.txt`.

## [v1.5.5] - 2026-09-29

### Fixed
- **Silent Auto-Updater Process Isolation & PyInstaller Environment Sanitization**:
  - Eliminated `Failed to load Python DLL (_MEI... python310.dll / LoadLibrary: Impossibile trovare il modulo specificato)` error on updater handover.
  - Recursively purges all PyInstaller bootloader variables (`_MEIPASS2`, `_MEIPASS`, `_PYI_PARENT_PROCESS_LEVEL`, `_PYI_ARCHIVE_FILE`, `_PYI_*`), Python environment overrides (`PYTHONPATH`, `PYTHONHOME`, `PYTHONEXECUTABLE`), and deleted `_MEI` temp directories from `PATH` in both Python and the PowerShell trampoline.
  - Switched trampoline process relaunch to direct process creation with a fully sanitized environment block (`UseShellExecute = $false`), preventing the freshly updated executable from mistaking itself for a child worker process of the terminated instance.
  - Enhanced process tree termination in updater trampoline to gracefully terminate any processes locking the target binary before applying the update.

## [v1.5.4] - 2026-09-29

### Fixed
- **Comprehensive Expedition Flag Alignment (57 Checkpoints across EN and IT)**:
  - Corrected official checkpoint and expedition flag names across 25 zones in both English and Italian.
  - Aligned names for Ancient Sanctuary (`RedForest` -> Entrance, `GiantBellAlley` -> Sanctuary Maze, `Arena` -> Giant Bell Alley), Esquie's Nest (`GestralEntry` -> Entrance, `Francois` -> Francois' Cave), Forgotten Battlefield, Frozen Hearts, Lumiere Act 3, Old Lumiere, Visages, Inside the Monolith, and single-entrance caverns.
  - Implemented zone-contextual resolution in `format_checkpoint_tag` preventing generic suffixes (e.g. `Arena`, `Plazza`, `Inside`, `Lake`, `Cave`) from colliding across maps.
- **Esquie's Nest & Francois' Cave Detection Bug**:
  - Resolved `LevelMain_EsquieNest` asset name regex mismatch in binary save reader that previously yielded `None` for level asset names.
  - Fixed detector gate `if cp_level and cp_tag:` so valid checkpoint tags are preserved even when map asset regex is non-standard.
  - Added semantic alias links in `SaveFileReader.is_checkpoint_for_zone` for `esquie`, `francois`, `yellowforest`, `chromazone`, `reacher`, `seacliff`, and `goblu`.
- **UE4SS Lua Bridge Mod Reflection Scanning**:
  - Added recursive `PropertyLink` reflection scan to `WBP_SavePointMenu_C` in `scripts/main.lua` to dynamically resolve save point subzone and checkpoint names directly from widget state.
  - Updated distribution bundle `bridge.zip` and synchronized active game installation scripts.
- **Automatic Bridge Checkpoint Normalization**:
  - Ensured all checkpoint telemetry emitted from the bridge mod is passed through `format_checkpoint_tag` for consistent localization and title cleanup.

## [v1.5.3] - 2026-09-29

### Fixed
- **Main Menu & Startup Telemetry Detection**:
  - Added native recognition for Unreal Engine startup bootstrap and main menu states (`Map_Game_Bootstrap`, `Bootstrap`, `MainMenu`, `Frontend`).
  - Emits dedicated Presence status ("Nel menu principale - Schermata dei titoli" / "In Main Menu - Title Screen") when the game launches, eliminating premature fallbacks to previous session save files on disk.
  - Implemented startup freshness validation preventing pre-launch save file fallback while the game is booting up.
  - Cleans up internal detector zone memory (`last_zone`, `last_raw_zone`) on game termination to avoid persisting previous session locations.
- **Continent Checkpoint Isolation & Map Transition Cleanup**:
  - Enforced strict checkpoint clearing whenever traveling to The Continent or transitioning between zones.
  - Eliminated orphaned checkpoint display on the overworld map (previously appending flags from departed dungeons such as `The Continent (Reverie Path)`).
  - Added on-screen widget visibility checks to the Lua bridge mod (`WBP_SavePointMenu_C:IsVisible()`) to prevent hidden/closed menu widgets from persisting checkpoint text.
  - Removed worldmap spawnpoint alias rules in the binary save reader that previously matched overworld maps.

## [v1.5.2] - 2026-09-29

### Fixed
- **Dynamic Windows Startup Path Synchronization**:
  - Automatically synchronizes and updates the Windows registry autostart entry (`HKCU\Software\Microsoft\Windows\CurrentVersion\Run`) to the active executable path whenever the app launches.
  - Resolves startup failures caused by moving the executable (e.g. from `Downloads` to `Desktop`) or stale registry paths.
  - Added existence verification in `is_startup_enabled()` to avoid showing active startup state when the registered binary path has been moved or deleted.
- **Cross-Filesystem Package Installation in uv**:
  - Configured `[tool.uv] link-mode = "copy"` in `pyproject.toml` to eliminate NTFS cross-device hardlink warnings when cache and project repositories reside on different drives (`C:` vs `D:`).

## [v1.5.1] - 2026-09-29

### Fixed
- **In-Game "Alpha" Naming Alignment for Chromatic Variant Enemies**:
  - Replaced all legacy and wiki references to "Chromatic" enemies with their official in-game designation ("Alpha"), including Endless Tower trial definitions and Super Boss encounters (e.g. *Alpha Lampmaster*, *Alpha Moissonneuse*, *Alpha Sakapatate*, *Alpha Chapelier*).
  - Corrected legacy wiki typo `Chromatic Chalier` to `Alpha Chapelier`.
  - Added autonomous normalization helper `format_enemy_name` to handle both English and Italian variants (`Chromatic`, `Cromatico/a/i/e` -> `Alpha`), ensuring compatibility with all game localizations and blueprint class names.
  - Updated embedded UE4SS combat bridge Lua script to directly emit official "Alpha" designations during live combat extraction.

## [v1.5.0] - 2026-09-26

### Added
- **Complete In-Game Expedition Flag Mapping (115 Flags across 48 Zones)**:
  - Exhaustive mapping of all 115 Expedition Flags with dual bilingual support (English and Italian).
  - Multi-tier dynamic resolution (`format_checkpoint_tag`): resolves full SpawnPoint tags, suffix tags, case-insensitive matches, and automatic CamelCase formatting for unmapped future flags.
  - Sub-area disambiguation (e.g. `Crumbling Path` in Sirene vs `Glissando` in Sirene's Dress; Monolith Exterior, Interior, and Peak entrance flags).
- **Official Zone Title Normalization**:
  - Direct translation of internal Unreal Engine map assets into player-facing titles (e.g. `Level_Goblu_Main` -> *Flying Waters*, `Level_SeaCliff` -> *Stone Wave Cliffs*, `Level_CleasFlyingHouse` -> *Flying Manor*, `Level_SimonArea` -> *The Abyss*, `Level_CleasTower` -> *Endless Tower*).
- **Process PID Binding for Discord Rich Presence**:
  - Bound Discord Rich Presence directly to the game's running process PID (`SandFall-Win64-Shipping.exe`) via `pypresence`, preventing collisions with Discord's default game detection.
- **Live Animated Discord Status Previews**:
  - Added authentic recorded animated GIFs (`preview_combat.gif`, `preview_tower.gif`, `preview_antispoiler.gif`) capturing live transitions between exploration, turn-based combat, Endless Tower multi-target trial encounters, and Anti-Spoiler mode.
- **Automated Security Verification & Antivirus Transparency**:
  - Published verified permanent VirusTotal report links for both `Expedition33_RPC.exe` (66/71 clean) and `bridge.zip` (67/68 clean).
  - Added comprehensive technical false-positive disclosures explaining Microsoft Defender cloud ML heuristics (`Trojan:Win32/Wacatac.B!ml`), PyInstaller self-extracting packaging, static AI classifiers, and UE4SS DLL proxying.
  - Added dedicated [SECURITY.md](SECURITY.md) outlining private vulnerability reporting guidelines and build provenance.
- **Discord Developer Portal Compliance & Media Organization**:
  - Added [PRIVACY.md](PRIVACY.md) and [TERMS.md](TERMS.md) covering zero-telemetry local IPC execution, data privacy, and legal terms.
  - Partitioned project media into dedicated `docs/github/` (README official artwork banner and animated GIF previews) and `docs/discord_portal/` (official high-resolution transparent assets at 1024x1024 and 512x512).
- **GitHub Community Infrastructure & Issue Templates**:
  - Added structured GitHub issue form templates (`.github/ISSUE_TEMPLATE/bug_report.yml`, `feature_request.yml`, and `config.yml` linking to GitHub Discussions).
  - Added dedicated `💬 Issues, Feedback & Bug Reports` section in `README.md` with contribution guidelines and pre-submission checklists.
- **UI & Presentation Polish**:
  - Added a centered shields.io total downloads counter in matching `for-the-badge` style directly under the main download executable button.
  - Streamlined `🚀 Quick Start` instructions by removing the redundant manual Discord Registered Games toggle, leveraging autonomous process PID binding.

### Fixed
- **Internal SpawnPoint Enemy Tag Disambiguation (`The Indigo Tree`)**:
  - Corrected tag mapping for The Indigo Tree in Spring Meadows where the internal Unreal Engine level design tagged the spawn point as `Level.SpawnPoint.SpringMeadows.Eveque` (after the Eveque mini-boss guarding the tree), which previously triggered a fallback display of `Spring Meadows (Eveque)`.
- **Single-Entrance Zone Flag Normalization**:
  - Resolved zone entry checkpoints that previously defaulted to generic `(Entrance)` instead of their official in-game flag names (e.g. `Dark Shores` -> `Bloodied Beach`, `Coastal Cave` -> `Forge`, `Sunless Cliffs` -> `Chroma Portal`, `Esoteric Ruins` -> `Lumiere Wrecks`, `The Abyss` -> `Simon`, `Painting Workshop` -> `Broken Conception`).
- **PyInstaller Environment Inheritance on Self-Update**:
  - Eliminated `_MEIPASS2` and `_MEIPASS` environment variable leakage from the parent process during self-update, ensuring the freshly updated executable generates a clean temporary runtime directory without `LoadLibrary` (`python310.dll`) collisions.

### Changed
- **100% Silent PowerShell Auto-Updater Trampoline**:
  - Replaced legacy `cmd.exe / .bat` switch script with an invisible native Windows PowerShell runner (`-WindowStyle Hidden`, `CREATE_NO_WINDOW`).
  - Eliminates flashing black console windows, incorporates file-lock retry loops, adds an antivirus settlement pause, and ensures completely autonomous process relaunch via Windows Shell (`Start-Process`).
- **Modular 4-Tier Architecture Refactoring**:
  - Restructured monolithic detector and root files into four distinct logical modules:
    - `core/`: Application lifecycle, single-instance mutex, Windows startup, and settings.
    - `detection/`: Memory detection, save file parsing, checkpoint resolution, and zone timer tracker.
    - `integrations/`: Discord RPC manager, UE4SS bridge installer, and GitHub release auto-updater.
    - `ui/`: System tray application, icon management, and dynamic context menus.
- **Documentation & Showcase Overhaul**:
  - Completely redesigned `README.md` featuring a horizontal side-by-side animated status showcase, comprehensive bilingual presence matrix (EN/IT), visual architecture tree, and system tray menu guide.
- **License Transition to MIT with Attribution**:
  - Updated the license terms to explicitly mandate visible attribution to the author (SolaneHub) and a direct repository link in all public distributions, forks, or derivative works.
- **CI/CD & Security Enhancements**:
  - Promoted `VT_API_KEY` to job-level environment in `.github/workflows/release.yml`, ensuring step-level conditionals reliably evaluate secret availability.
  - Included `bridge.zip` as a first-class release asset alongside `Expedition33_RPC.exe` and `SHA256SUMS.txt`.

## [v1.4.0] - 2026-09-24

### Added
- **Modern Packaging & Environment Architecture**:
  - Migrated build backend from legacy `setuptools` to `hatchling` (PEP 517/518/621/660), eliminating `*.egg-info` workspace pollution.
  - Adopted `uv` as the project package manager, featuring deterministic dependency resolution via `uv.lock` and Python version pinning to 3.10 via `.python-version`.
  - Adopted PEP 735 `[dependency-groups]` for development tooling (`pyinstaller`, `ruff`, `pyright`), enabling single-command `uv sync`.
- **Release Security & Cryptographic Verification**:
  - Automated SHA-256 checksum generation (`SHA256SUMS.txt`) included with all release artifacts and release notes.
  - GitHub Artifact Attestation (`actions/attest-build-provenance@v2` / Sigstore) for verifiable supply-chain security and build provenance.
  - Automated multi-engine antivirus scanning via VirusTotal (`crazy-max/ghaction-virustotal@v4`) integrated into the release pipeline.
- **Natural Bilingual Presence Phrasing**:
  - Refined combat status to natural gaming conventions:
    - English: `Fighting: <Enemy>` (in encounter) and `In Combat` (generic / anti-spoiler).
    - Italian: `In combattimento con: <Enemy>` (in encounter) and `In combattimento` (generic / anti-spoiler).
  - Enhanced tray status indicators to match the standardized combat phrasing.
- **Semi-Automatic In-App Auto-Updater**:
  - Implemented native `AppUpdater` communicating directly with GitHub Releases API with zero external dependencies.
  - Silent background check on startup with tray toast notification when a newer release is published.
  - Dynamic tray menu item: shows `Check for Updates` or `Update to vX.X.X [Install Now]` with live progress percentage.
  - Cryptographic integrity: verifies SHA-256 hash against `SHA256SUMS.txt` before applying the update.
  - Seamless Windows trampoline: safely replaces running `.exe` via detached switch script and restarts the app automatically.

### Changed
- **CI/CD Pipeline Modernization**:
  - Upgraded GitHub Actions release workflow to use `astral-sh/setup-uv@v5` with `--frozen` lockfile installation and automated pyright type validation.
- **Emoji Removal**:
  - Removed all emojis across application code, Discord presence strings, system tray labels, and documentation to ensure clean display and avoid Windows console encoding conflicts.
- **Code Quality & Linter Enforcement**:
  - Enabled Ruff `ARG` rule (`flake8-unused-arguments`) and VS Code `reportUnusedParameter` severity override to automatically flag unused parameters as warnings.
  - Standardized all `pystray` system tray callbacks, actions, and lambdas to use the catch-all `*_` signature, and replaced the `MenuItem as item` import alias with direct `MenuItem` usage, completely eliminating unused parameter and import warnings across both Pylance and Ruff.
- **Documentation & Configuration Cleanup**:
  - Completely restructured `README.md` with focused installation, security transparency, and tray controls reference.
  - Streamlined `.gitignore` and `pyproject.toml` exclude rules, removing legacy virtualenv, setuptools, and unused cache patterns while tracking `.vscode/settings.json`.

## [v1.3.0] - 2026-09-24

### Added
- **Dynamic Zone Extraction from HUD Widgets**:
  - Zone names are now read directly from the in-game on-screen HUD widgets (`WBP_HUD_LevelNameAnnounce_C`, `WBP_Exploration_HUD_C`, etc.) using UMG property reflection.
  - Displays the official localized zone name exactly as the game shows it (e.g., `Bozze di Verso` in Italian) — no hardcoded dictionaries or manual translations.
  - Falls back to cleaned `UWorld` persistent level name if no HUD widget is active.
- **Real-Time Enemy Name Extraction**:
  - Extracts enemy names during turn-based combat from `AC_jRPG_BattleManager_C.Enemies[]` on the Game Thread.
  - Resolves clean names from actor class Blueprint identifiers (e.g., `BP_Enemy_Battle_Barbasucette_C` → `Barbasucette`, `BP_EnemyBattle_Licorne_C` → `Licorne`).
  - Multi-target grouping with count badges (`Barbasucette, Licorne x2`) and length formatting for Discord Rich Presence.
  - Periodically re-checks enemies every 3 seconds during combat to reflect defeated enemies in real time.
- **Unified Anti-Spoiler Mode**:
  - Interactive toggle button in the tray context menu (`Anti-Spoiler Mode`).
  - Concurrently obscures both enemy names and location zones to prevent story spoilers.
  - Seamless persistence across restarts via Windows Registry (`HKCU\Software\Expedition33_RPC\AntiSpoiler`).

### Fixed
- **Eliminated UObject Pointer Leaks in Enemy Names**:
  - Removed unsafe `tostring()` fallback on UObject property accesses that produced raw memory pointers (`UObject: 0x...`) instead of readable names.
  - Added strict rejection filters for any string containing `UObject:` or `0x` in both the Lua bridge and the Python detector.
- **Engine Crash Prevention**:
  - Eliminated all unsafe StringTable and async UObject dereference calls from the Lua bridge that previously triggered `0xC0000005` Fatal Errors during enemy spawn transitions.
  - All UObject actor access is now exclusively performed within `ExecuteInGameThread()` callbacks.

### Changed
- **Fully Dynamic Localization**: Removed all hardcoded zone name dictionaries (`OFFICIAL_ZONE_NAMES_IT`, manual translations). Everything is extracted dynamically from the running game.
- **UE4SS Hot Reload Enabled**: `EnableHotReloadSystem` set to `1` in `UE4SS-settings.ini`, allowing in-game script reload with `Ctrl+R` without restarting.

## [v1.2.0] - 2026-09-24

### Added
- **Enemy Combat Name Extraction**:
  - Real-time extraction of enemy and boss names during turn-based encounters (e.g., `Fighting: Francois`, `Fighting: Goblu x2`).
  - Resilient multi-tier extraction pipeline querying localized `CharacterName`, `EnemyName`, battle stats components, and cleaned Blueprint actor identifiers.
  - Multi-target grouping with count badges (`x2`, `x3`) and length formatting for Discord Rich Presence.
- **Unified Anti-Spoiler Mode**:
  - Interactive toggle button in the tray context menu (`Anti-Spoiler Mode  [Enabled] / [Disabled]`).
  - Concurrently obscures both enemy names and location zones to prevent story spoilers:
    - Encounters masked to generic `In Combat` (`In combattimento`).
    - Locations masked to `Hidden Location` (`Posizione riservata`).
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
  - Context menu toggle in the system tray (`Combat Bridge`) for instant verification, installation, or uninstallation.

## [v1.0.0] - 2026-09-23

### Added
- **Autonomous Game Detection**: Automatic detection of *Clair Obscur: Expedition 33* (`SandFall-Win64-Shipping.exe`) process with continuous background polling.
- **Dynamic Discord Rich Presence**:
  - Live zone & location tracking extracted in real time from `SavesContainer.sav`.
  - Automatic game language detection (`GameUserSettings.ini`) and localized area name formatting.
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

