"""Real loopback IPC transport mock server for Discord Rich Presence testing.

Provides an in-process mock server for Discord IPC communicating over
native Windows named pipes or Unix domain sockets.
"""

from __future__ import annotations

import contextlib
import json
import os
import socket
import struct
import sys
import tempfile
import threading
import uuid
from collections.abc import Callable
from typing import Any

from expedition33_rpc.integrations.discord_rpc import OP_FRAME, OP_HANDSHAKE

if sys.platform == "win32":
    import _winapi  # type: ignore[import-not-found]
    import ctypes


class MockDiscordServer:
    """Cross-platform loopback IPC server mimicking the Discord Rich Presence daemon.

    Runs in a background thread and serves Discord IPC clients using:
    - Named pipes on Windows (`\\\\.\\pipe\\...`)
    - Unix domain sockets on Linux and macOS
    """

    def __init__(
        self,
        pipe_path: str | None = None,
        handler: Callable[[int, dict[str, Any]], tuple[int, dict[str, Any]] | None] | None = None,
    ) -> None:
        self.handler = handler
        self._lock = threading.Lock()
        self._ready_event = threading.Event()
        self._running = False
        self._thread: threading.Thread | None = None
        self._temp_dir: tempfile.TemporaryDirectory[str] | None = None
        self.received_frames: list[tuple[int, dict[str, Any]]] = []
        self.connection_count: int = 0

        self._current_handle: int | None = None
        self._server_sock: Any = None

        if pipe_path is not None:
            self.pipe_path = pipe_path
        elif sys.platform == "win32":
            unique_id = uuid.uuid4().hex[:12]
            self.pipe_path = rf"\\.\pipe\test-discord-ipc-{unique_id}"
        else:
            self._temp_dir = tempfile.TemporaryDirectory()
            unique_id = uuid.uuid4().hex[:12]
            self.pipe_path = os.path.join(self._temp_dir.name, f"discord-ipc-{unique_id}")

    def __enter__(self) -> MockDiscordServer:
        self.start()
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.stop()

    def start(self, timeout: float = 5.0) -> None:
        """Starts the mock server thread and waits until it is ready to accept connections."""
        if self._running:
            return
        self._running = True
        self._ready_event.clear()

        target = self._run_windows if sys.platform == "win32" else self._run_unix
        self._thread = threading.Thread(target=target, daemon=True, name="MockDiscordServerThread")
        self._thread.start()

        if not self._ready_event.wait(timeout=timeout):
            self.stop()
            raise TimeoutError("MockDiscordServer failed to initialize within timeout")

    def stop(self) -> None:
        """Stops the mock server, closes transport handles, and cleans up temporary files."""
        if not self._running:
            return
        self._running = False

        if sys.platform == "win32":
            if self._current_handle is not None:
                with contextlib.suppress(Exception), open(self.pipe_path, "r+b", buffering=0):
                    pass
        else:
            if self._server_sock is not None:
                with contextlib.suppress(Exception):
                    self._server_sock.close()

        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=3.0)
        self._thread = None

        if self._temp_dir is not None:
            with contextlib.suppress(Exception):
                self._temp_dir.cleanup()
            self._temp_dir = None

    def clear_frames(self) -> None:
        """Clears all captured incoming frames."""
        with self._lock:
            self.received_frames.clear()

    def get_frames(self) -> list[tuple[int, dict[str, Any]]]:
        """Returns a snapshot copy of all frames captured by the mock server."""
        with self._lock:
            return list(self.received_frames)

    def _default_handler(
        self, opcode: int, payload: dict[str, Any]
    ) -> tuple[int, dict[str, Any]] | None:
        if opcode == OP_HANDSHAKE:
            return (
                OP_FRAME,
                {
                    "cmd": "DISPATCH",
                    "evt": "READY",
                    "data": {
                        "v": 1,
                        "config": {
                            "cdn_host": "cdn.discordapp.com",
                            "api_endpoint": "//discord.com/api",
                            "environment": "production",
                        },
                        "user": {
                            "id": payload.get("client_id", "123456789"),
                            "username": "Expeditionist",
                        },
                    },
                },
            )
        elif opcode == OP_FRAME:
            cmd = payload.get("cmd", "")
            if cmd == "SET_ACTIVITY":
                return (
                    OP_FRAME,
                    {
                        "cmd": "SET_ACTIVITY",
                        "data": payload.get("args", {}).get("activity"),
                        "evt": None,
                        "nonce": payload.get("nonce"),
                    },
                )
            return (OP_FRAME, {"cmd": cmd, "data": {}, "nonce": payload.get("nonce")})
        return None

    # ---------------------------------------------------------------------------
    # Windows Transport
    # ---------------------------------------------------------------------------

    def _win_read_exact(self, handle: int, n: int) -> bytes:
        buf = bytearray()
        while len(buf) < n and self._running:
            chunk, _err = _winapi.ReadFile(handle, n - len(buf))
            if not chunk:
                raise EOFError("Named pipe closed by remote peer")
            buf.extend(chunk)
        if len(buf) < n:
            raise EOFError("Named pipe closed prematurely")
        return bytes(buf)

    def _run_windows(self) -> None:
        pipe_handle = _winapi.CreateNamedPipe(
            self.pipe_path,
            _winapi.PIPE_ACCESS_DUPLEX,
            0,
            1,
            4096,
            4096,
            0,
            _winapi.NULL,
        )
        self._current_handle = pipe_handle
        self._ready_event.set()

        try:
            while self._running:
                try:
                    _winapi.ConnectNamedPipe(pipe_handle, overlapped=False)
                except OSError as e:
                    if getattr(e, "winerror", None) == _winapi.ERROR_PIPE_CONNECTED:
                        pass
                    else:
                        break

                if not self._running:
                    break

                with self._lock:
                    self.connection_count += 1

                try:
                    while self._running:
                        header = self._win_read_exact(pipe_handle, 8)
                        op, length = struct.unpack("<II", header)
                        body_bytes = self._win_read_exact(pipe_handle, length)
                        payload = json.loads(body_bytes.decode("utf-8"))

                        with self._lock:
                            self.received_frames.append((op, payload))

                        resp = (
                            self.handler(op, payload)
                            if self.handler
                            else self._default_handler(op, payload)
                        )
                        if resp is not None:
                            resp_op, resp_payload = resp
                            resp_data = json.dumps(resp_payload, separators=(",", ":")).encode(
                                "utf-8"
                            )
                            resp_header = struct.pack("<II", resp_op, len(resp_data))
                            _winapi.WriteFile(pipe_handle, resp_header + resp_data)
                except (BrokenPipeError, EOFError, OSError):
                    pass
                finally:
                    if self._running:
                        ctypes.windll.kernel32.DisconnectNamedPipe(pipe_handle)
        finally:
            with contextlib.suppress(Exception):
                ctypes.windll.kernel32.DisconnectNamedPipe(pipe_handle)
            with contextlib.suppress(Exception):
                _winapi.CloseHandle(pipe_handle)
            self._current_handle = None

    # ---------------------------------------------------------------------------
    # Unix Transport
    # ---------------------------------------------------------------------------

    def _sock_read_exact(self, conn: Any, n: int) -> bytes:
        buf = bytearray()
        while len(buf) < n and self._running:
            try:
                chunk = conn.recv(n - len(buf))
                if not chunk:
                    raise EOFError("Unix socket closed by remote peer")
                buf.extend(chunk)
            except TimeoutError:
                if not self._running:
                    raise EOFError("Server stopped") from None
                continue
        if len(buf) < n:
            raise EOFError("Unix socket closed prematurely")
        return bytes(buf)

    def _run_unix(self) -> None:
        af_unix = getattr(socket, "AF_UNIX", socket.AF_INET)
        server_sock = socket.socket(af_unix, socket.SOCK_STREAM)
        self._server_sock = server_sock
        with contextlib.suppress(Exception):
            if os.path.exists(self.pipe_path):
                os.unlink(self.pipe_path)
        server_sock.bind(self.pipe_path)
        server_sock.listen(5)
        server_sock.settimeout(0.2)
        self._ready_event.set()

        try:
            while self._running:
                try:
                    conn, _ = server_sock.accept()
                except TimeoutError:
                    continue
                except OSError:
                    break

                if not self._running:
                    break

                with self._lock:
                    self.connection_count += 1

                conn.settimeout(0.5)
                try:
                    while self._running:
                        header = self._sock_read_exact(conn, 8)
                        op, length = struct.unpack("<II", header)
                        body_bytes = self._sock_read_exact(conn, length)
                        payload = json.loads(body_bytes.decode("utf-8"))

                        with self._lock:
                            self.received_frames.append((op, payload))

                        resp = (
                            self.handler(op, payload)
                            if self.handler
                            else self._default_handler(op, payload)
                        )
                        if resp is not None:
                            resp_op, resp_payload = resp
                            resp_data = json.dumps(resp_payload, separators=(",", ":")).encode(
                                "utf-8"
                            )
                            resp_header = struct.pack("<II", resp_op, len(resp_data))
                            conn.sendall(resp_header + resp_data)
                except (BrokenPipeError, EOFError, OSError):
                    pass
                finally:
                    with contextlib.suppress(Exception):
                        conn.close()
        finally:
            with contextlib.suppress(Exception):
                server_sock.close()
            with contextlib.suppress(Exception):
                if os.path.exists(self.pipe_path):
                    os.unlink(self.pipe_path)
            self._server_sock = None


__all__ = ["MockDiscordServer"]
