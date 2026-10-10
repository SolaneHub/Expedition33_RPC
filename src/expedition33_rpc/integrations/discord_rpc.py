"""Native Discord IPC client and Rich Presence manager for Expedition 33.

Implements the Discord RPC IPC wire protocol directly over local named pipes (Windows)
and Unix domain sockets without third-party dependencies or asynchronous event loops.
"""

from __future__ import annotations

import contextlib
import ctypes
import json
import os
import socket
import struct
import sys
import threading
import time
import uuid
from typing import Any, BinaryIO, Protocol

if sys.platform == "win32":
    import msvcrt
else:
    msvcrt = None  # type: ignore[assignment]

from expedition33_rpc.detection.detector import GameState
from expedition33_rpc.ui.presentation import format_presence, truncate_presence_field

EMBEDDED_CLIENT_ID = "1552405358503272468"

OP_HANDSHAKE = 0
OP_FRAME = 1
OP_CLOSE = 2
OP_PING = 3
OP_PONG = 4


class IPCTransport(Protocol):
    """Type-safe bidirectional transport protocol for Discord IPC communication."""

    def read(self, n: int) -> bytes: ...

    def write(self, data: bytes) -> int: ...

    def close(self) -> None: ...


class DiscordIPCClient:
    """Lightweight, synchronous Discord IPC client speaking the native binary RPC wire protocol."""

    def __init__(
        self,
        client_id: str = EMBEDDED_CLIENT_ID,
        custom_pipe_path: str | None = None,
        transport: IPCTransport | None = None,
        timeout: float = 2.0,
    ):
        self.client_id = client_id
        self.custom_pipe_path = custom_pipe_path
        self._transport: IPCTransport | None = transport
        self.timeout = timeout
        self._pipe: IPCTransport | BinaryIO | None = None
        self._sock: socket.socket | None = None
        self.is_connected: bool = False
        self._lock = threading.RLock()

    def _candidate_pipe_paths(self) -> list[str]:
        if self.custom_pipe_path:
            return [self.custom_pipe_path]
        if sys.platform == "win32":
            return [rf"\\.\pipe\discord-ipc-{i}" for i in range(10)]

        env_keys = ["XDG_RUNTIME_DIR", "TMPDIR", "TMP", "TEMP"]
        dirs = [os.environ[k] for k in env_keys if k in os.environ] + ["/tmp"]
        candidates: list[str] = []
        for d in dirs:
            for i in range(10):
                candidate = os.path.join(d, f"discord-ipc-{i}")
                if candidate not in candidates:
                    candidates.append(candidate)
        return candidates

    def _send(self, opcode: int, payload: dict[str, Any]) -> None:
        with self._lock:
            if not self._pipe:
                raise ConnectionError("Not connected to Discord IPC pipe")
            data = json.dumps(payload, separators=(",", ":")).encode("utf-8")
            header = struct.pack("<II", opcode, len(data))
            self._pipe.write(header + data)

    def _read_exact(self, n: int) -> bytes:
        """Reads exactly n bytes from the underlying pipe/socket stream, handling chunked delivery and timeouts."""
        if not self._pipe:
            raise ConnectionError("Not connected to Discord IPC pipe")
        buf = bytearray()
        deadline = time.monotonic() + self.timeout
        while len(buf) < n:
            remaining = n - len(buf)
            if sys.platform == "win32" and msvcrt is not None:
                fileno_fn = getattr(self._pipe, "fileno", None)
                if callable(fileno_fn):
                    handle = None
                    try:
                        fd = fileno_fn()
                        if isinstance(fd, int):
                            handle = msvcrt.get_osfhandle(fd)
                    except (AttributeError, OSError, ValueError):
                        pass

                    if handle is not None and handle != -1:
                        avail = ctypes.c_ulong(0)
                        while time.monotonic() < deadline:
                            res = ctypes.windll.kernel32.PeekNamedPipe(
                                handle, None, 0, None, ctypes.byref(avail), None
                            )
                            if res == 0:
                                raise ConnectionError("Named pipe broken or closed")
                            if avail.value > 0:
                                break
                            time.sleep(0.01)
                        else:
                            raise TimeoutError(f"Discord IPC read timed out after {self.timeout}s")

            chunk = self._pipe.read(remaining)
            if not chunk:
                raise ConnectionError("Incomplete IPC stream received from Discord")
            buf.extend(chunk)
        return bytes(buf)

    def _recv(self) -> tuple[int, dict[str, Any]]:
        with self._lock:
            header = self._read_exact(8)
            opcode, length = struct.unpack("<II", header)
            body = self._read_exact(length)
            return opcode, json.loads(body.decode("utf-8"))

    def connect(self) -> bool:
        """Attempts connection and protocol handshake with Discord IPC."""
        with self._lock:
            if self.is_connected:
                return True

            if self._transport is not None:
                try:
                    self._pipe = self._transport
                    # Handshake
                    self._send(OP_HANDSHAKE, {"v": 1, "client_id": self.client_id})
                    op, resp = self._recv()
                    if op == OP_FRAME and (
                        resp.get("evt") == "READY" or resp.get("cmd") == "DISPATCH"
                    ):
                        self.is_connected = True
                        return True
                    self.close()
                    return False
                except Exception:
                    self.close()
                    return False

            for path in self._candidate_pipe_paths():
                attempts = 5 if self.custom_pipe_path else 1
                for attempt in range(attempts):
                    sock: socket.socket | None = None
                    try:
                        if sys.platform == "win32":
                            pipe: BinaryIO = open(path, "r+b", buffering=0)  # noqa: SIM115
                        else:
                            sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                            sock.settimeout(self.timeout)
                            sock.connect(path)
                            pipe = sock.makefile("rwb", buffering=0)  # type: ignore
                            self._sock = sock
                        self._pipe = pipe

                        # Handshake
                        self._send(OP_HANDSHAKE, {"v": 1, "client_id": self.client_id})
                        op, resp = self._recv()
                        if op == OP_FRAME and (
                            resp.get("evt") == "READY" or resp.get("cmd") == "DISPATCH"
                        ):
                            self.is_connected = True
                            return True
                        self.close()
                    except (OSError, ValueError, ConnectionError):
                        if sock is not None:
                            with contextlib.suppress(Exception):
                                sock.close()
                        self.close()
                        if attempt < attempts - 1:
                            time.sleep(0.025)
                        continue

            return False

    def close(self) -> None:
        """Closes the active IPC pipe and resets state."""
        with self._lock:
            if self._pipe:
                with contextlib.suppress(Exception):
                    self._pipe.close()
            if self._sock:
                with contextlib.suppress(Exception):
                    self._sock.close()
            self._sock = None
            self._pipe = None
            self.is_connected = False

    def set_activity(
        self,
        pid: int,
        state: str,
        details: str,
        start_timestamp: int | None = None,
        large_image: str = "logo",
        large_text: str = "Clair Obscur: Expedition 33",
    ) -> bool:
        """Sends a SET_ACTIVITY frame to Discord atomically."""
        activity: dict[str, Any] = {
            "state": state,
            "details": details,
            "assets": {
                "large_image": large_image,
                "large_text": large_text,
            },
        }
        if start_timestamp:
            activity["timestamps"] = {"start": start_timestamp}

        payload = {
            "cmd": "SET_ACTIVITY",
            "args": {
                "pid": pid,
                "activity": activity,
            },
            "nonce": str(uuid.uuid4()),
        }
        with self._lock:
            try:
                self._send(OP_FRAME, payload)
                _op, _resp = self._recv()
                return True
            except Exception:
                self.close()
                return False

    def clear_activity(self, pid: int) -> bool:
        """Clears the currently displayed Rich Presence activity atomically."""
        payload = {
            "cmd": "SET_ACTIVITY",
            "args": {
                "pid": pid,
                "activity": None,
            },
            "nonce": str(uuid.uuid4()),
        }
        with self._lock:
            try:
                self._send(OP_FRAME, payload)
                _op, _resp = self._recv()
                return True
            except Exception:
                self.close()
                return False


class DiscordRPCManager:
    """Coordinates presence formatting, rate-limiting, and lifecycle management with Discord."""

    def __init__(
        self,
        client: DiscordIPCClient | None = None,
    ) -> None:
        self.client_id: str = EMBEDDED_CLIENT_ID
        self._client: DiscordIPCClient | None = client
        self._rpc: DiscordIPCClient | None = client
        self.is_connected: bool = client.is_connected if client is not None else False
        self.last_update_state: str | None = None
        self.last_retry_time: float = 0.0
        self._lock = threading.RLock()

    @property
    def rpc(self) -> DiscordIPCClient | None:
        return self._rpc

    def connect(self) -> bool:
        with self._lock:
            if self.is_connected and self._rpc is not None and self._rpc.is_connected:
                return True

            now = time.time()
            if now - self.last_retry_time < 5.0:
                return False
            self.last_retry_time = now

            try:
                if self._rpc is None:
                    self._rpc = (
                        self._client
                        if self._client is not None
                        else DiscordIPCClient(self.client_id)
                    )
                res = self._rpc.connect()
                self.is_connected = bool(
                    getattr(self._rpc, "is_connected", True) if res is None else res
                )
                if self.is_connected:
                    print(f"[DiscordRPC] Connected to Discord IPC (Client ID: {self.client_id})")
                elif self._client is None:
                    self._rpc = None
                return self.is_connected
            except Exception:
                self.is_connected = False
                if self._client is None:
                    self._rpc = None
                return False

    def disconnect(self) -> None:
        with self._lock:
            if self._rpc:
                with contextlib.suppress(Exception):
                    self._rpc.clear_activity(pid=os.getpid())
                    self._rpc.close()
            self._rpc = None
            self.is_connected = False

    def reconnect(self) -> None:
        with self._lock:
            self.disconnect()
            self.connect()

    def invalidate(self) -> None:
        """Clears the cached presence fingerprint, forcing re-transmission on the next update."""
        with self._lock:
            self.last_update_state = None

    def update(
        self,
        game_state: GameState,
        anti_spoiler: bool = False,
        force: bool = False,
    ) -> None:
        """Formats and transmits the latest presence data to Discord."""
        with self._lock:
            if force:
                self.last_update_state = None

            if not self.is_connected and not self.connect():
                return

            target_pid = (
                game_state.process_pid
                if (game_state.process_pid and game_state.process_pid > 0)
                else os.getpid()
            )

            if not game_state.is_running:
                if self.last_update_state != "idle" and self._rpc:
                    try:
                        success = self._rpc.clear_activity(pid=target_pid)
                        if success:
                            self.last_update_state = "idle"
                        else:
                            self.is_connected = False
                    except Exception:
                        self.is_connected = False
                return

            details_text, state_text = format_presence(game_state, anti_spoiler=anti_spoiler)
            details_text = truncate_presence_field(details_text)
            state_text = truncate_presence_field(state_text)

            start_timestamp = (
                int(game_state.start_time) if game_state.start_time else int(time.time())
            )

            # State fingerprint to avoid redundant IPC writes
            fingerprint = f"{details_text}|{state_text}|{start_timestamp}|{target_pid}"
            if fingerprint == self.last_update_state:
                return

            if self._rpc:
                try:
                    success = self._rpc.set_activity(
                        pid=target_pid,
                        state=state_text,
                        details=details_text,
                        start_timestamp=start_timestamp,
                        large_image="logo",
                        large_text="Clair Obscur: Expedition 33",
                    )
                    if success:
                        self.last_update_state = fingerprint
                        print(f"[DiscordRPC] Status updated: {details_text} - {state_text}")
                    else:
                        self.is_connected = False
                except Exception as e:
                    print(f"[DiscordRPC] RPC update error: {e}")
                    self.is_connected = False


__all__ = [
    "EMBEDDED_CLIENT_ID",
    "OP_CLOSE",
    "OP_FRAME",
    "OP_HANDSHAKE",
    "OP_PING",
    "OP_PONG",
    "IPCTransport",
    "DiscordIPCClient",
    "DiscordRPCManager",
]
