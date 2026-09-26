# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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

