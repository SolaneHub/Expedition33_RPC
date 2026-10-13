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
from collections.abc import Callable
from typing import Any, BinaryIO, Protocol

from expedition33_rpc.core.presence import PresencePayload

msvcrt: Any = None
if sys.platform == "win32":
    import msvcrt
else:
    msvcrt = None

EMBEDDED_CLIENT_ID = "1552405358503272468"

OP_HANDSHAKE = 0
OP_FRAME = 1
OP_CLOSE = 2
OP_PING = 3
OP_PONG = 4


class DiscordFrameCodec:
    """Centralized wire codec for Discord IPC binary frame serialization."""

    HEADER_SIZE: int = 8
    HEADER_FORMAT: str = "<II"

    @classmethod
    def encode(cls, op: int, payload: dict[str, Any]) -> bytes:
        """Packs opcode and JSON payload into Discord wire frame bytes."""
        data = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        header = struct.pack(cls.HEADER_FORMAT, op, len(data))
        return header + data

    @classmethod
    def decode(cls, data: bytes | bytearray) -> tuple[int, dict[str, Any]]:
        """Unpacks full Discord wire frame bytes into (opcode, payload)."""
        if len(data) < cls.HEADER_SIZE:
            raise ValueError(f"Insufficient data for frame header: {len(data)} < {cls.HEADER_SIZE}")
        op, length = struct.unpack(cls.HEADER_FORMAT, data[: cls.HEADER_SIZE])
        if len(data) < cls.HEADER_SIZE + length:
            raise ValueError(
                f"Truncated frame payload: expected {length} bytes, got {len(data) - cls.HEADER_SIZE}"
            )
        body = data[cls.HEADER_SIZE : cls.HEADER_SIZE + length]
        return op, json.loads(body.decode("utf-8"))

    @classmethod
    def decode_header(cls, header_bytes: bytes | bytearray) -> tuple[int, int]:
        """Decodes the 8-byte header into (opcode, payload_length)."""
        if len(header_bytes) < cls.HEADER_SIZE:
            raise ValueError(
                f"Insufficient data for header: {len(header_bytes)} < {cls.HEADER_SIZE}"
            )
        return struct.unpack(cls.HEADER_FORMAT, header_bytes[: cls.HEADER_SIZE])


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
            self._pipe.write(DiscordFrameCodec.encode(opcode, payload))

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
            header = self._read_exact(DiscordFrameCodec.HEADER_SIZE)
            _op, length = DiscordFrameCodec.decode_header(header)
            body = self._read_exact(length)
            return DiscordFrameCodec.decode(header + body)

    def connect(self, attempts: int | None = None) -> bool:
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

            num_attempts = attempts if attempts is not None else (5 if self.custom_pipe_path else 1)
            for path in self._candidate_pipe_paths():
                for attempt in range(num_attempts):
                    sock: socket.socket | None = None
                    try:
                        if sys.platform == "win32":
                            pipe: IPCTransport | BinaryIO = open(path, "r+b", buffering=0)  # noqa: SIM115
                        else:
                            sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                            sock.settimeout(self.timeout)
                            sock.connect(path)
                            pipe = sock.makefile("rwb", buffering=0)
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
                        if attempt < num_attempts - 1:
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
        state: str | None = None,
        details: str | None = None,
        start_timestamp: int | None = None,
        large_image: str | None = "logo",
        large_text: str | None = "Clair Obscur: Expedition 33",
        small_image: str | None = None,
        small_text: str | None = None,
        party_id: str | None = None,
        party_size: tuple[int, int] | None = None,
    ) -> bool:
        """Sends a SET_ACTIVITY frame to Discord atomically."""
        assets: dict[str, Any] = {}
        if large_image:
            assets["large_image"] = large_image
        if large_text:
            assets["large_text"] = large_text
        if small_image:
            assets["small_image"] = small_image
        if small_text:
            assets["small_text"] = small_text

        activity: dict[str, Any] = {
            "state": state,
            "details": details,
            "assets": assets,
        }
        if start_timestamp:
            activity["timestamps"] = {"start": start_timestamp}
        if party_id and party_size:
            activity["party"] = {"id": party_id, "size": list(party_size)}

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

    is_stopping: Callable[[], bool] | None = None

    def __init__(
        self,
        client: DiscordIPCClient | None = None,
        is_stopping: Callable[[], bool] | None = None,
    ) -> None:
        self.client_id: str = EMBEDDED_CLIENT_ID
        self._client: DiscordIPCClient | None = client
        self._rpc: DiscordIPCClient | None = client
        self.last_update_state: str | None = None
        self.last_retry_time: float = 0.0
        self.is_stopping: Callable[[], bool] | None = is_stopping

    @property
    def rpc(self) -> DiscordIPCClient | None:
        return self._rpc

    @property
    def is_connected(self) -> bool:
        return self._rpc is not None and self._rpc.is_connected

    @is_connected.setter
    def is_connected(self, value: bool) -> None:
        if self._rpc is not None:
            self._rpc.is_connected = value

    def connect(self) -> bool:
        if self.is_stopping is not None and self.is_stopping():
            return False

        if self.is_connected:
            return True

        now = time.time()
        if now - self.last_retry_time < 5.0:
            return False
        self.last_retry_time = now

        try:
            if self._rpc is None:
                self._rpc = (
                    self._client if self._client is not None else DiscordIPCClient(self.client_id)
                )
            res = self._rpc.connect()
            connected = bool(getattr(self._rpc, "is_connected", True) if res is None else res)
            if connected:
                print(f"[DiscordRPC] Connected to Discord IPC (Client ID: {self.client_id})")
            elif self._client is None:
                self._rpc = None
            return connected
        except Exception:
            if self._client is None:
                self._rpc = None
            return False

    def disconnect(self) -> None:
        if self._rpc:
            with contextlib.suppress(Exception):
                self._rpc.clear_activity(pid=os.getpid())
                self._rpc.close()
        self._rpc = None

    def reconnect(self) -> None:
        self.disconnect()
        self.connect()

    def invalidate(self) -> None:
        """Clears the cached presence fingerprint, forcing re-transmission on the next update."""
        self.last_update_state = None

    def update_presence(
        self,
        payload: PresencePayload | None,
        pid: int | None = None,
        force: bool = False,
    ) -> bool:
        """Transmits the latest presence data to Discord."""

        if self.is_stopping is not None and self.is_stopping():
            return False

        if force:
            self.last_update_state = None

        if not self.is_connected:
            if self.is_stopping is not None and self.is_stopping():
                return False
            if not self.connect():
                return False

        target_pid = pid if (pid and pid > 0) else os.getpid()

        if payload is None:
            if self.last_update_state != "idle" and self._rpc:
                try:
                    success = self._rpc.clear_activity(pid=target_pid)
                    if success:
                        self.last_update_state = "idle"
                        return True
                    else:
                        self.is_connected = False
                        return False
                except Exception:
                    self.is_connected = False
                    return False
            return True

        details_text = payload.details[:128] if payload.details else None
        state_text = payload.state[:128] if payload.state else None
        start_timestamp = (
            payload.start_timestamp if payload.start_timestamp is not None else int(time.time())
        )
        large_image = payload.large_image or "logo"
        large_text = payload.large_text or "Clair Obscur: Expedition 33"

        # State fingerprint to avoid redundant IPC writes
        fingerprint = f"{details_text}|{state_text}|{start_timestamp}|{large_image}|{target_pid}"
        if fingerprint == self.last_update_state:
            return True

        if self._rpc:
            try:
                success = self._rpc.set_activity(
                    pid=target_pid,
                    state=state_text,
                    details=details_text,
                    start_timestamp=start_timestamp,
                    large_image=large_image,
                    large_text=large_text,
                    small_image=payload.small_image,
                    small_text=payload.small_text,
                    party_id=payload.party_id,
                    party_size=payload.party_size,
                )
                if success:
                    self.last_update_state = fingerprint
                    print(f"[DiscordRPC] Status updated: {details_text} - {state_text}")
                    return True
                else:
                    self.is_connected = False
                    return False
            except Exception as e:
                print(f"[DiscordRPC] RPC update error: {e}")
                self.is_connected = False
                return False
        return False

    def update(
        self,
        payload: PresencePayload | None,
        pid: int | None = None,
        force: bool = False,
    ) -> bool:
        """Alias for update_presence accepting PresencePayload."""
        return self.update_presence(payload, pid=pid, force=force)


__all__ = [
    "EMBEDDED_CLIENT_ID",
    "OP_CLOSE",
    "OP_FRAME",
    "OP_HANDSHAKE",
    "OP_PING",
    "OP_PONG",
    "DiscordFrameCodec",
    "IPCTransport",
    "DiscordIPCClient",
    "DiscordRPCManager",
]
