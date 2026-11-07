# Expedition33_RPC Architecture

Expedition33_RPC is a native, lightweight Windows and POSIX daemon for Discord Rich Presence tailored for *Clair Obscur: Expedition 33*. It reads real-time telemetry from the Unreal Engine 5 runtime, normalizes it through static Single Source of Truth (SSOT) catalogs, and transmits it directly to the local Discord client over Named Pipes without external dependencies or asynchronous runtime overhead.

---

## 1. Mental Model and Design Philosophy

The architecture adheres to three core engineering principles:

1. **Zero Game Footprint**: No process injection, no external DLL hooks. Hot telemetry is emitted asynchronously by the game (via a lightweight UE4SS Lua mod) into an IPC file in `%TEMP%`. The RPC daemon reads this file using Win32 non-blocking shared reads (`FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE`).
2. **Deterministic Tiered Fallback**: If the Lua bridge mod is missing or unresponsive, the system gracefully degrades by reading binary Unreal Engine 5 save files (`.sav`) via memory mapping (`mmap`).
3. **Pure Functional Pipelines**: Every polling tick creates an immutable Data Transfer Object (`GameState`), processed through pure normalization routines (`ui/presentation.py`) before serializing binary frames to Discord.

---

## 2. End-to-End Data Pipeline

The animated diagram below illustrates the live data lifecycle from in-game telemetry through detection, normalization, and output to Discord:

<p align="center">
  <img src="docs/architecture_pipeline.svg" alt="Expedition 33 End-to-End Telemetry Pipeline" width="100%">
</p>

### Data Lifecycle Stages:
1. **Hot Telemetry Generation**: The client-side Lua mod writes atomic state frames directly to `%TEMP%\expedition33_status.json`.
2. **Non-Blocking Ingestion**: `BridgeStateProvider` opens the status file using Win32 `CreateFileW` with `0x7` flags (`FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE`), preventing file lock contention while the game writes.
3. **Emergency Fallback**: If the Lua mod is inactive or its checkpoint string is empty, `SaveFileReader` inspects binary `.sav` files on disk using `mmap` to retrieve `LastUsedSavePoint`.
4. **State Normalization**: `GameDetector` verifies freshness (5.0s SLA) and builds an immutable `GameState` snapshot via pure catalog mappings in `game_data.json`.
5. **Presence Delivery**: `AppOrchestrator` formats text fields according to Discord's 128-byte boundary rules and serializes `<II` binary frames to the local named pipe.

---

## 3. Threading Model and Platform Abstraction

The daemon avoids heavy runtime systems, isolating blocking I/O and UI loops into dedicated execution threads:

| Thread | Lifecycle | Purpose & Scope |
| :--- | :--- | :--- |
| **Main Thread** | Application lifetime | Acquires single-instance lock, bootstraps `AppOrchestrator`, and runs the `pystray` Win32 message pump. |
| **Worker Loop** | Background daemon | Drives periodic polling: process detection, telemetry consumption, state normalization, and presence dispatch. |
| **Auto-Installer** | Ephemeral worker | Spawns upon discovering a new game PID to copy UE4SS bridge assets into the game's `Win64` directory. |
| **Updater Thread** | Ephemeral worker | Checks GitHub Releases in the background to prevent network latency from blocking the main loop. |

<p align="center">
  <img src="docs/architecture_threading.svg" alt="Expedition 33 Threading & Platform Abstraction" width="100%">
</p>

---

## 4. Telemetry Boundary: Hot Path vs. Emergency Fallback

The detection subsystem uses an asymmetric tiered strategy to maximize telemetry accuracy while maintaining zero overhead:

| Feature | Hot Path: `BridgeStateProvider` | Emergency Fallback: `SaveFileReader` |
| :--- | :--- | :--- |
| **Channel** | Local IPC file (`%TEMP%\expedition33_status.json`) | UE5 `.sav` binary on disk (`%LOCALAPPDATA%\Sandfall\Saved\SaveGames\...`) |
| **I/O Mechanism** | Win32 `CreateFileW` with share flags `0x7` (`FILE_SHARE_READ \| FILE_SHARE_WRITE \| FILE_SHARE_DELETE`) | `mmap.mmap` read-only token scanning |
| **Frequency / Latency** | Every active tick (2.0s) / `< 1 ms` | Lazy on-demand: executed only when bridge telemetry lacks active checkpoint |
| **Freshness SLA** | **5.0 seconds**: if `timestamp` differs from `now()` by `> 5.0s`, data is discarded as stale | Cached by `(mtime, size)` to prevent re-reading identical save files |
| **Extracted State** | Active zone, combat status, enemy names, Endless Tower floor/trial, active checkpoint | Level name and spawn point (`LastUsedSavePoint`, `LevelAssetName`, `SpawnPoint`) |

---

## 5. Frozen Contracts (Non-Negotiable)

Any modification or refactoring must preserve these four contracts without divergence.

### 5.1. IPC JSON Schema (`%TEMP%\expedition33_status.json`)

Written by the UE4SS Lua bridge mod in UTF-8 without BOM:

```json
{
  "timestamp": 1727788800.0,
  "raw_zone": "Level_Main_OldLumiere",
  "zone": "Level_Main_OldLumiere",
  "in_combat": true,
  "enemy_name": "Duollistes",
  "enemies": ["Duollistes", "Glaive"],
  "checkpoint": "Level.SpawnPoint.Camp01",
  "floor": null,
  "tower_floor": null,
  "tower_trial": [11, 3]
}
```

- `timestamp`: Mandatory Unix epoch float used by the 5.0s freshness filter.
- `raw_zone` / `zone`: Raw Unreal Engine map identifier.
- `in_combat`: Boolean toggling exploration vs. combat presence templates.
- `checkpoint`: Raw spawn point / flag tag.

### 5.2. Discord Named Pipe Binary Frame (`<II`)

Discord exposes a local IPC pipe on Windows (`\\.\pipe\discord-ipc-0` through `9`) and a Unix domain socket on POSIX. Every packet MUST conform to the native 8-byte binary layout:

```text
┌───────────────────────┬───────────────────────┬───────────────────────────────────────┐
│ Opcode (uint32 LE)    │ Length (uint32 LE)    │ JSON Payload (UTF-8, "Length" bytes)  │
│ 4 Bytes               │ 4 Bytes               │ Serialized JSON (separators: ',',':') │
├───────────────────────┴───────────────────────┴───────────────────────────────────────┤
│ <II Binary Header (8 Bytes)                   │ Body Data                             │
└───────────────────────────────────────────────┴───────────────────────────────────────┘
```

Standard Opcodes:
- `OP_HANDSHAKE = 0`: Initial handshake payload (`{"v": 1, "client_id": "..."}`)
- `OP_FRAME = 1`: Rich Presence activity frame (`SET_ACTIVITY`)
- `OP_CLOSE = 2`: Pipe closure
- `OP_PING = 3` / `OP_PONG = 4`: IPC heartbeat

*Discord Limit*: Strings in `details` and `state` must not exceed **128 UTF-8 bytes**. `truncate_presence_field` truncates directly on byte boundaries without breaking multibyte code points.

### 5.3. Static SSOT Catalog (`game_data.json`)

All mapping tables reside strictly in `src/expedition33_rpc/assets/game_data.json`. CI tests (`tests/ci/test_game_data_schema.py`) enforce the presence and consistency of:

- `target_process_names`: Known game binaries (e.g. `sandfall-win64-shipping.exe`).
- `main_menu_tokens`: Substrings identifying title, loading, or splash screens.
- `localized_presentation`: Bilingual (`en-US`, `it`) templates (`exploring`, `fighting`, `stage_trial`).
- `zone_name_overrides_by_lang`: Mapping from raw level tokens to localized names.
- `checkpoint_names_by_lang`: Mapping from UE5 spawn tags to human-readable names.
- `endless_tower_trials`: Static table for Endless Tower trial and boss matching.

### 5.4. Windows Autostart Registry Contract

System startup registration targets `HKEY_CURRENT_USER` (requiring no elevated UAC permissions):

```text
Hive:      HKEY_CURRENT_USER
Subkey:    Software\Microsoft\Windows\CurrentVersion\Run
Value:     Expedition33_DiscordRPC
Type:      REG_SZ
Content:   "C:\Path\To\Expedition33_RPC.exe" (Quoted absolute path)
```

In development environments, the command points to the windowless Python executable (`pythonw.exe`) to prevent terminal consoles from opening upon Windows logon.
