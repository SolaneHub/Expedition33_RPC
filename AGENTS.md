# AI Agent & Developer Directives: Expedition33_RPC

Imperative directives for LLMs and developers modifying this codebase. Zero ambiguity, zero fluff.

## 1. Development & Quality Commands

Always verify changes using [`uv`](https://github.com/astral-sh/uv). Never push unverified code.

- **Fast Track (Pre-commit Runner - SLA < 2.5s)**:
  `uv run python tools/pre_commit.py`
  *(Runs `ruff check`, `ruff format --check`, `pyright`, and `pytest -m unit` with fail-fast semantics)*
- **4-Tier Verification Matrix (`tools/run_matrix.py`)**:
  - `uv run python tools/run_matrix.py --tier fast` *(SLA < 2.5s: lint, format, pyright, unit)*
  - `uv run python tools/run_matrix.py --tier pr` *(SLA < 8.0s: fast + integration + `build_bridge_zip.py --check`)*
  - `uv run python tools/run_matrix.py --tier release` *(SLA < 15.0s: pr + CI tests + Win/Linux pyright + prettier + game_data + smoke)*
  - `uv run python tools/run_matrix.py --tier soak` *(Opt-in: soak tests + save reader dormancy)*
- **Bridge Mod Parity**:
  `uv run python tools/build_bridge_zip.py --check` *(verifies `bridge/scripts/main.lua` matches `assets/bridge.zip`)*

## 2. Core Engineering Directives

1. **Radical Feature Parsimony (YAGNI)**: Reject speculative abstractions, unrequested config knobs, and speculative payload fields (`party_id`, `party_size`, `small_image`, `small_text` are permanently pruned).
2. **6-Tier Acyclic DAG (AST-Enforced)**: Lower tiers never import higher tiers (`test_strict_6_tier_dag_hierarchy`):
   - Tier 0: `_version`, `core/platform`, `core/resources`, `core/settings`, `detection/timer_tracker`
   - Tier 1: `detection/game_data`, `core/startup`, `integrations/updater`
   - Tier 2: `detection/normalization`, `detection/steam_resolver`
   - Tier 3: `detection/detector`, `detection/save_reader`, `core/presence`
   - Tier 4: `ui/presentation`, `integrations/discord_rpc`, `integrations/bridge_installer`
   - Tier 5: `core/orchestrator`, `ui/tray_app`, `core/smoke`, `core/app`, `__main__`, `__init__`
3. **Resource-Critical Loop Protection**:
   - *Idle*: 5.0s sleep, query only process names/PIDs via `psutil`. *Active*: 2.0s poll, O(1) `cached_pid` check.
   - *Telemetry Ingestion*: Non-blocking Win32 `0x7` (`_read_file_shared_text` / `open_file_shared_binary` in `SaveFileReader`) taking < 1 ms; 5.0s TTL freshness; `has_received_telemetry` prevents `is_starting` regression.
   - *Clock Decoupling*: `monotonic_provider` (`time.monotonic()`) for internal timers/deadlines/cooldowns; `epoch_provider` (`time.time()`) strictly for Discord `timestamps.start` and telemetry TTL. Never mix domains.
   - *Async Boundaries*: `UpdaterProtocol` runs in background thread (3.0s delay); `DiscordRPCManager` dirty-checks frames, caps `MAX_FRAME_LENGTH` (1 MiB), and handles `evt="ERROR"`.
4. **Dry-Run & Integration-First**: Test observable contracts via `tests/harness/` (`FakeProcess`, `GameSessionSimulator`, `DiscordPipeSimulator`, `HeadlessTrayHarness`, `DualClockHarness`, `FakeWinreg`, `FakeHttpOpener`).
5. **Hard Stop on Semi-Reversible Choices**: Never add dependencies to `pyproject.toml` (frozen 3 runtime + 4 dev), alter `expedition33_status.json` schema, or mutate Discord `<II` framing without explicit approval.
6. **Zero Suppressed Warnings & Zero Shims**: 100% Pyright `standard` compliance (`reportUnknownArgumentType`, `reportUnknownVariableType`). Zero `type: ignore`, `# noqa`, `compat_paths.py`, manual `.spec`, or re-export shims.

## 3. Code Conventions

- **Python 3.12+**: PEP 695 `type` aliases, `@override`, built-in generics, `match ... case`.
- **Cross-Platform Primitives**: Route all OS-level calls (`ctypes`, `winreg`, `flock`, `0x7` shared reads) through `core/platform.py`.
