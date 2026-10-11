import threading
from typing import Any

from expedition33_rpc.integrations.discord_rpc import (
    OP_FRAME,
    OP_HANDSHAKE,
    DiscordFrameCodec,
)


class DiscordPipeSimulator:
    """Simulates an OS named pipe connection to Discord IPC daemon.

    Supports thread-safe buffering of outgoing frames written by DiscordIPCClient
    and feeding queued or auto-generated incoming response frames.
    """

    def __init__(
        self,
        incoming_data: bytes = b"",
        auto_respond_set_activity: bool = False,
    ):
        self._lock = threading.Lock()
        self.incoming_bytes = bytearray(incoming_data)
        self.outgoing_bytes = bytearray()
        self.auto_respond_set_activity = auto_respond_set_activity
        self.is_closed = False

    def queue_response(self, data: dict[str, Any], op: int = OP_FRAME) -> None:
        """Pushes an IPC frame into the receive buffer for the client to read."""
        with self._lock:
            self.incoming_bytes.extend(DiscordFrameCodec.encode(op, data))

    def write(self, data: bytes) -> int:
        """Called by the client when sending bytes into the pipe."""
        with self._lock:
            self.outgoing_bytes.extend(data)
            if self.auto_respond_set_activity:
                is_handshake = False
                if len(data) >= DiscordFrameCodec.HEADER_SIZE:
                    op, _ = DiscordFrameCodec.decode_header(data[: DiscordFrameCodec.HEADER_SIZE])
                    if op == OP_HANDSHAKE:
                        is_handshake = True
                if is_handshake:
                    resp_payload = {"cmd": "DISPATCH", "evt": "READY", "data": {}}
                else:
                    resp_payload = {"cmd": "SET_ACTIVITY", "data": {}}
                self.incoming_bytes.extend(DiscordFrameCodec.encode(OP_FRAME, resp_payload))
        return len(data)

    def read(self, n: int = -1) -> bytes:
        """Called by the client when receiving bytes from the pipe."""
        with self._lock:
            if n == -1 or n >= len(self.incoming_bytes):
                res = bytes(self.incoming_bytes)
                self.incoming_bytes.clear()
                return res
            res = bytes(self.incoming_bytes[:n])
            del self.incoming_bytes[:n]
            return res

    def close(self) -> None:
        with self._lock:
            self.is_closed = True

    @property
    def written_data(self) -> bytes:
        with self._lock:
            return bytes(self.outgoing_bytes)

    def pop_last_frame_payload(self) -> dict[str, Any] | None:
        """Extracts and decodes the oldest pending frame written by the client."""
        with self._lock:
            if len(self.outgoing_bytes) < DiscordFrameCodec.HEADER_SIZE:
                return None
            _out_op, out_len = DiscordFrameCodec.decode_header(
                bytes(self.outgoing_bytes[: DiscordFrameCodec.HEADER_SIZE])
            )
            total_frame_len = DiscordFrameCodec.HEADER_SIZE + out_len
            if len(self.outgoing_bytes) < total_frame_len:
                return None
            frame_bytes = bytes(self.outgoing_bytes[:total_frame_len])
            del self.outgoing_bytes[:total_frame_len]
            _op, payload = DiscordFrameCodec.decode(frame_bytes)
            return payload

    def drain_all_frames(self) -> list[tuple[int, dict[str, Any]]]:
        """Extracts and decodes all pending frames, verifying binary integrity."""
        frames: list[tuple[int, dict[str, Any]]] = []
        with self._lock:
            idx = 0
            data = bytes(self.outgoing_bytes)
            while idx + DiscordFrameCodec.HEADER_SIZE <= len(data):
                _op, length = DiscordFrameCodec.decode_header(
                    data[idx : idx + DiscordFrameCodec.HEADER_SIZE]
                )
                total_frame_len = DiscordFrameCodec.HEADER_SIZE + length
                if idx + total_frame_len > len(data):
                    raise ValueError(
                        f"Truncated frame payload: expected {length} bytes at offset {idx}"
                    )
                frame_bytes = data[idx : idx + total_frame_len]
                idx += total_frame_len
                frames.append(DiscordFrameCodec.decode(frame_bytes))
            if idx != len(data):
                raise ValueError(
                    f"Incomplete trailing bytes in pipe: {len(data) - idx} bytes remaining"
                )
            self.outgoing_bytes.clear()
        return frames
