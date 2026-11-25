"""Native Discord IPC client and Rich Presence manager for Expedition 33.

Implements the Discord RPC IPC wire protocol directly over local named pipes (Windows)
and Unix domain sockets without third-party dependencies or asynchronous event loops.
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import random
import struct
import sys
import threading
import time
import uuid
from collections.abc import Callable
from typing import Any, BinaryIO, Protocol, cast

import expedition33_rpc.core.platform as platform
from expedition33_rpc.core.presence import PresencePayload, truncate_presence_field

logger = logging.getLogger(__name__)

EMBEDDED_CLIENT_ID = "1552405358503272468"

OP_HANDSHAKE = 0
OP_FRAME = 1
OP_CLOSE = 2
OP_PING = 3
OP_PONG = 4
VALID_OPCODES: frozenset[int] = frozenset({OP_HANDSHAKE, OP_FRAME, OP_CLOSE, OP_PING, OP_PONG})


class DiscordFrameCodec:
    """Centralized wire codec for Discord IPC binary frame serialization."""

    HEADER_SIZE: int = 8
    HEADER_FORMAT: str = "<II"
    MAX_FRAME_LENGTH: int = 1_048_576

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
        if length > cls.MAX_FRAME_LENGTH:
            raise ValueError(
                f"Discord IPC frame length {length} exceeds maximum allowed {cls.MAX_FRAME_LENGTH}"
            )
        if len(data) < cls.HEADER_SIZE + length:
            raise ValueError(
                f"Truncated frame payload: expected {length} bytes, got {len(data) - cls.HEADER_SIZE}"
            )
        body = data[cls.HEADER_SIZE : cls.HEADER_SIZE + length]
        if not body:
            return op, {}
        decoded: Any = json.loads(body.decode("utf-8"))
        if not isinstance(decoded, dict):
            raise ValueError(
                f"Expected JSON object payload in Discord IPC frame, got {type(decoded).__name__}"
            )
        return op, cast(dict[str, Any], decoded)

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
        monotonic_provider: Callable[[], float] | None = None,
    ):
        self.client_id = client_id
        self.custom_pipe_path = custom_pipe_path
        self._transport: IPCTransport | None = transport
        self.timeout = timeout
        self.monotonic_provider: Callable[[], float] = (
            monotonic_provider if monotonic_provider is not None else time.monotonic
        )
        self._pipe: IPCTransport | BinaryIO | None = None
        self._sock: Any = None
        self.is_connected: bool = False
        self._lock = threading.RLock()

    @property
    def transport(self) -> IPCTransport | None:
        return self._transport

    @transport.setter
    def transport(self, transport: IPCTransport | None) -> None:
        self._transport = transport

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
        deadline = self.monotonic_provider() + self.timeout
        while len(buf) < n:
            now = self.monotonic_provider()
            if len(buf) > 0 and now >= deadline:
                raise TimeoutError(f"Discord IPC read timed out after {self.timeout}s")
            remaining = n - len(buf)
            remaining_time = max(0.0, deadline - now)
            if not platform.peek_named_pipe_ready(
                self._pipe,
                timeout=remaining_time,
                monotonic_provider=self.monotonic_provider,
            ):
                raise TimeoutError(f"Discord IPC read timed out after {self.timeout}s")

            chunk = self._pipe.read(remaining)
            if not chunk:
                raise ConnectionError("Incomplete IPC stream received from Discord")
            buf.extend(chunk)
        return bytes(buf)

    def _recv(self) -> tuple[int, dict[str, Any]]:
        with self._lock:
            while True:
                header = self._read_exact(DiscordFrameCodec.HEADER_SIZE)
                _op, length = DiscordFrameCodec.decode_header(header)
                if length > DiscordFrameCodec.MAX_FRAME_LENGTH:
                    raise ValueError(
                        f"Discord IPC frame length {length} exceeds maximum allowed "
                        f"{DiscordFrameCodec.MAX_FRAME_LENGTH}"
                    )
                body = self._read_exact(length)
                op, payload = DiscordFrameCodec.decode(header + body)

                if op == OP_PING:
                    self._send(OP_PONG, payload)
                    continue

                if op == OP_CLOSE:
                    self.close()
                    raise ConnectionError("Discord closed IPC connection")

                return op, payload

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

            if self._pipe is not None or self._sock is not None:
                self.close()

            num_attempts = attempts if attempts is not None else (5 if self.custom_pipe_path else 1)
            for path in self._candidate_pipe_paths():
                for attempt in range(num_attempts):
                    sock: Any = None
                    try:
                        opened: Any = platform.open_discord_pipe(path, timeout=self.timeout)
                        if hasattr(opened, "makefile"):
                            sock = opened
                            pipe: IPCTransport | BinaryIO = opened.makefile("rwb", buffering=0)
                            self._sock = sock
                        else:
                            pipe = opened
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
                    except Exception:
                        if sock is not None:
                            with contextlib.suppress(Exception):
                                sock.close()
                        self.close()
                        raise

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

    def read_frame(self) -> tuple[int, dict[str, Any]]:
        """Receives and decodes the next Discord IPC frame."""
        return self._recv()

    def set_activity(
        self,
        pid: int,
        state: str | None = None,
        details: str | None = None,
        start_timestamp: int | None = None,
        large_image: str | None = "logo",
        large_text: str | None = "Clair Obscur: Expedition 33",
    ) -> bool:
        """Sends a SET_ACTIVITY frame to Discord atomically."""
        assets: dict[str, Any] = {}
        if large_image:
            assets["large_image"] = large_image
        if large_text:
            assets["large_text"] = large_text

        activity: dict[str, Any] = {
            "state": state,
            "details": details,
            "assets": assets,
        }
        if start_timestamp:
            activity["timestamps"] = {"start": start_timestamp}

        payload: dict[str, Any] = {
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
                _op, resp = self._recv()
                if isinstance(resp, dict) and resp.get("evt") == "ERROR":
                    logger.error("Discord IPC SET_ACTIVITY error: %s", resp.get("data", resp))
                    if self._transport is None:
                        self.close()
                    return False
                return True
            except Exception:
                self.close()
                return False

    def clear_activity(self, pid: int) -> bool:
        """Clears the currently displayed Rich Presence activity atomically."""
        payload: dict[str, Any] = {
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
                _op, resp = self._recv()
                if isinstance(resp, dict) and resp.get("evt") == "ERROR":
                    logger.error("Discord IPC clear_activity error: %s", resp.get("data", resp))
                    if self._transport is None:
                        self.close()
                    return False
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
        monotonic_provider: Callable[[], float] | None = None,
        epoch_provider: Callable[[], float] | None = None,
        jitter_provider: Callable[[float, float], float] | None = None,
    ) -> None:
        self.client_id: str = EMBEDDED_CLIENT_ID
        self.monotonic_provider: Callable[[], float] = (
            monotonic_provider if monotonic_provider is not None else time.monotonic
        )
        self.epoch_provider: Callable[[], float] = (
            epoch_provider if epoch_provider is not None else time.time
        )
        self.jitter_provider: Callable[[float, float], float] = (
            jitter_provider if jitter_provider is not None else random.uniform
        )
        self._is_injected_client: bool = client is not None
        self._client: DiscordIPCClient = (
            client
            if client is not None
            else DiscordIPCClient(self.client_id, monotonic_provider=self.monotonic_provider)
        )
        self._io_lock = threading.RLock()
        self._state_lock = threading.Lock()
        self.last_update_state: str | None = None
        self.last_retry_time: float = 0.0
        self._retry_failures: int = 0
        self.base_retry_interval: float = 5.0
        self.is_stopping: Callable[[], bool] | None = is_stopping
        self._last_target_pid: int | None = None

    @property
    def is_injected_client(self) -> bool:
        with self._state_lock:
            return self._is_injected_client

    @property
    def retry_failures(self) -> int:
        with self._state_lock:
            return self._retry_failures

    @retry_failures.setter
    def retry_failures(self, value: int) -> None:
        with self._state_lock:
            self._retry_failures = value

    @property
    def last_target_pid(self) -> int | None:
        with self._state_lock:
            return self._last_target_pid

    @property
    def client(self) -> DiscordIPCClient:
        with self._state_lock:
            return self._client

    @client.setter
    def client(self, client: DiscordIPCClient | None) -> None:
        with self._state_lock:
            if client is not None:
                self._is_injected_client = True
                self._client = client
            else:
                self._is_injected_client = False
                self._client = DiscordIPCClient(
                    self.client_id, monotonic_provider=self.monotonic_provider
                )

    @property
    def is_connected(self) -> bool:
        with self._state_lock:
            return self._client.is_connected

    def connect(self) -> bool:
        if self.is_stopping is not None and self.is_stopping():
            return False

        with self._io_lock:
            if self.is_stopping is not None and self.is_stopping():
                return False

            with self._state_lock:
                if self._client.is_connected:
                    return True

                now = self.monotonic_provider()
                if self._retry_failures > 0 and self.last_retry_time != 0.0:
                    delay = min(
                        30.0, self.base_retry_interval * (2 ** max(0, self._retry_failures - 1))
                    )
                    if self._retry_failures > 1:
                        delay += self.jitter_provider(0.0, 0.5)
                    if now - self.last_retry_time < delay:
                        return False

                client = self._client
                is_injected = self._is_injected_client

            try:
                if not is_injected and not client.is_connected:
                    with contextlib.suppress(Exception):
                        client.close()
                    new_client = DiscordIPCClient(
                        self.client_id, monotonic_provider=self.monotonic_provider
                    )
                    with self._state_lock:
                        if not self._is_injected_client:
                            self._client = new_client
                            client = new_client
                res = client.connect()
                connected = bool(getattr(client, "is_connected", True) if res is None else res)
                if not connected and not is_injected:
                    with contextlib.suppress(Exception):
                        client.close()
                with self._state_lock:
                    if connected:
                        self._retry_failures = 0
                        self.last_retry_time = 0.0
                        logger.info("Connected to Discord IPC (Client ID: %s)", self.client_id)
                    else:
                        self._retry_failures += 1
                        self.last_retry_time = now
                        if not self._is_injected_client:
                            self._client = DiscordIPCClient(
                                self.client_id, monotonic_provider=self.monotonic_provider
                            )
                return connected
            except Exception:
                if not is_injected:
                    with contextlib.suppress(Exception):
                        client.close()
                with self._state_lock:
                    self._retry_failures += 1
                    self.last_retry_time = now
                    if not self._is_injected_client:
                        self._client = DiscordIPCClient(
                            self.client_id, monotonic_provider=self.monotonic_provider
                        )
                return False

    def disconnect(self) -> None:
        with self._io_lock:
            with self._state_lock:
                self._retry_failures = 0
                self.last_retry_time = 0.0
                self.last_update_state = None
                client = self._client
                is_injected = self._is_injected_client
                target_pid = self._last_target_pid or os.getpid()

            try:
                with contextlib.suppress(Exception):
                    client.clear_activity(pid=target_pid)
            finally:
                with contextlib.suppress(Exception):
                    client.close()

            with self._state_lock:
                self.last_update_state = None
                if not is_injected and not self._is_injected_client:
                    self._client = DiscordIPCClient(
                        self.client_id, monotonic_provider=self.monotonic_provider
                    )

    def reconnect(self) -> None:
        with self._io_lock:
            self.disconnect()
            with self._state_lock:
                self.last_retry_time = 0.0
            self.connect()

    def invalidate(self) -> None:
        """Clears the cached presence fingerprint, forcing re-transmission on the next update."""
        with self._state_lock:
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

        with self._io_lock:
            if self.is_stopping is not None and self.is_stopping():
                return False

            if force:
                with self._state_lock:
                    self.last_update_state = None

            if not self.is_connected:
                if self.is_stopping is not None and self.is_stopping():
                    return False
                if not self.connect():
                    return False

            target_pid = pid if (pid and pid > 0) else os.getpid()

            if payload is None:
                with self._state_lock:
                    already_idle = self.last_update_state == "idle"
                    client = self._client
                if not already_idle:
                    try:
                        success = client.clear_activity(pid=target_pid)
                        if not success and client.transport is None:
                            with contextlib.suppress(Exception):
                                client.close()
                        with self._state_lock:
                            if success:
                                self.last_update_state = "idle"
                                self._last_target_pid = target_pid
                                return True
                            else:
                                self._client.is_connected = False
                                return False
                    except Exception:
                        if client.transport is None:
                            with contextlib.suppress(Exception):
                                client.close()
                        with self._state_lock:
                            self._client.is_connected = False
                        return False
                return True

            details_text = truncate_presence_field(payload.details) if payload.details else None
            state_text = truncate_presence_field(payload.state) if payload.state else None
            start_timestamp = payload.start_timestamp
            large_image = payload.large_image or "logo"
            large_text = payload.large_text or "Clair Obscur: Expedition 33"

            # State fingerprint to avoid redundant IPC writes
            fingerprint = (
                f"{details_text}|{state_text}|{start_timestamp}|{large_image}|"
                f"{large_text}|{target_pid}"
            )
            with self._state_lock:
                if fingerprint == self.last_update_state:
                    self._last_target_pid = target_pid
                    return True
                client = self._client

            try:
                success = client.set_activity(
                    pid=target_pid,
                    state=state_text,
                    details=details_text,
                    start_timestamp=start_timestamp,
                    large_image=large_image,
                    large_text=large_text,
                )
                if not success and client.transport is None:
                    with contextlib.suppress(Exception):
                        client.close()
                with self._state_lock:
                    if success:
                        self.last_update_state = fingerprint
                        self._last_target_pid = target_pid
                        logger.info("Status updated: %s - %s", details_text, state_text)
                        return True
                    else:
                        self._client.is_connected = False
                        return False
            except Exception as e:
                logger.error("RPC update error: %s", e)
                if client.transport is None:
                    with contextlib.suppress(Exception):
                        client.close()
                with self._state_lock:
                    self._client.is_connected = False
                return False


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
