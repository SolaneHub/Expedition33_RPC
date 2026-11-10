# AI Agent & Developer Directives: Expedition33_RPC

Imperative directives for LLMs and developers modifying this codebase. Zero ambiguity, zero fluff.

## 1. Development & Quality Commands

Always verify changes using [`uv`](https://github.com/astral-sh/uv). Never push unverified code.

- **Fast Track (Pre-commit / Iteration)**:
  `uv run ruff check && uv run pytest -m unit`
- **Full Matrix (Strict Gatekeeper)**:
  `uv run ruff check && uv run ruff format --check && uv run pyright && uv run pytest && npx prettier --check src/expedition33_rpc/assets/game_data.json`

## 2. Core Engineering Directives for AI Agents

1. **Radical Feature Parsimony (YAGNI)**: Reject speculative abstractions, unrequested config knobs, and architectural over-engineering. Solve the immediate task with minimal state and minimal code footprint.
2. **Resource-Critical Loop Protection**: Zero unnecessary overhead in the polling engine:
   - *Idle State* (game not detected): 5.0s sleep interval, query only process names/PIDs via `psutil`.
   - *Active State* (game running): 2.0s polling interval with O(1) PID liveness checks on `cached_pid`.
   - *Telemetry Ingestion*: Non-blocking Win32 `CreateFileW` with `FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE` (flags `0x7`) taking < 1 ms.
   - *Telemetry Heartbeat*: The Lua mod continuously emits heartbeat frames during combat to ensure the 5.0s TTL freshness SLA is satisfied across prolonged encounters.
   - *Checkpoint & Save Resolution*: When bridge checkpoint data is empty, query `SaveFileReader` with O(1) `st_mtime` file caching. Never disable save reader fallback based on active telemetry alone without explicit bridge checkpoint tokens.
   - *Startup & Ingestion Lifecycle*: Track process telemetry arrival via `has_received_telemetry`. The `is_starting` state is strictly reserved for initial launch before the first telemetry frame arrives (remains `True` until the first actual frame); never regress to `is_starting` during transient stalls or empty frames.
   - *Clock Decoupling*: Strict separation of time domains. Use `time.monotonic()` for all internal timers, polling intervals, idle backoff, reconnection retries, thread join deadlines, and cooldowns. Use `time.time()` (epoch seconds) strictly for outbound Discord Rich Presence wire frames (`timestamps.start`) and telemetry timestamp freshness. Never compare or mix monotonic timestamps with epoch timestamps.
   - *Update Engine Decoupling*: Decouple update checking from the polling engine via `UpdaterProtocol`. Background checks must run asynchronously in a dedicated worker thread with delayed execution (3.0s), never blocking or injecting latency into the telemetry polling loop.
   - *Bridge Installation*: Background daemon thread with strict cooldown and retry limits.
   - *Discord IPC*: Dirty-checking on outbound frames; never send identical presence payloads.
3. **Dry-Run & Integration-First**: Test observable system behavior and interface contracts, not brittle private methods. Use `FakeProcess`, `GameSessionSimulator`, `DiscordPipeSimulator & MockDiscordServer`, `HeadlessTrayHarness`, `FakeUpdater`, and `FakeBridgeInstaller` from `tests/harness/` and `tests/` for deterministic testing.
4. **Hard Stop on Semi-Reversible Choices**: Never add dependencies to `pyproject.toml`, alter the external IPC status JSON schema, or mutate the Discord binary `<II` wire frame layout without explicit human approval.
5. **Zero Suppressed Warnings**: 100% strict type safety under Pyright (`typeCheckingMode = "standard"`). Absolutely zero `type: ignore`, `# noqa`, or unjustified Ruff suppressions across the codebase.

## 3. Code Conventions

- **Language Runtime**: Python 3.12+ standard syntax.
- **Modern Typing**: PEP 695 type aliases (`type PresenceDict = dict[str, Any]`), `typing.override` on overrides, and built-in generics (`list[str]`, `dict[str, Any]`, `tuple[int, int] | None`).
- **Control Flow**: Prefer structural pattern matching (`match ... case`) and pure functional transforms over deep conditional trees.
- **Cross-Platform Primitives**: Route all OS-level calls (mutexes, locks, registry, file sharing) through `core/platform.py`. Never invoke raw `ctypes`, `winreg`, or POSIX locks inside domain logic.
