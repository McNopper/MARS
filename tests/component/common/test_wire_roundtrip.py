"""Component tests: wire framing helpers over a real asyncio TCP connection.

These exercise :func:`write_frame`, :func:`read_frame` and :func:`iter_frames`
end-to-end across an actual socket pair (not fakes), proving the framing the
whole MARS transport relies on survives real reads/writes and partial flushes.
"""

from __future__ import annotations

import asyncio
import contextlib

from mars.common.wire import iter_frames, read_frame, write_frame


async def _socket_pair() -> tuple[
    asyncio.StreamReader, asyncio.StreamWriter,  # client side
    asyncio.StreamReader, asyncio.StreamWriter,  # server side
    asyncio.AbstractServer,
]:
    """Open a loopback server and a connected client; return both stream pairs."""
    accepted: asyncio.Queue = asyncio.Queue()

    async def _on_conn(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        await accepted.put((reader, writer))

    server = await asyncio.start_server(_on_conn, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    c_reader, c_writer = await asyncio.open_connection("127.0.0.1", port)
    s_reader, s_writer = await accepted.get()
    return c_reader, c_writer, s_reader, s_writer, server


async def _close(*items) -> None:
    for it in items:
        if isinstance(it, asyncio.StreamWriter):
            it.close()
            with contextlib.suppress(Exception):
                await it.wait_closed()
        elif isinstance(it, asyncio.AbstractServer):
            it.close()
            with contextlib.suppress(Exception):
                await it.wait_closed()


class TestWireOverRealSocket:
    async def test_single_frame_round_trip(self):
        c_reader, c_writer, s_reader, s_writer, server = await _socket_pair()
        try:
            ok = await write_frame(c_writer, {"t": "hello", "name": "cli"})
            assert ok is True
            frame = await read_frame(s_reader)
            assert frame == {"t": "hello", "name": "cli"}
        finally:
            await _close(c_writer, s_writer, server)

    async def test_multiple_frames_preserve_order(self):
        c_reader, c_writer, s_reader, s_writer, server = await _socket_pair()
        try:
            sent = [{"t": "msg", "n": i} for i in range(5)]
            for payload in sent:
                await write_frame(c_writer, payload)
            c_writer.write_eof()

            received = [f async for f in iter_frames(s_reader)]
            assert received == sent
        finally:
            await _close(c_writer, s_writer, server)

    async def test_bidirectional_exchange(self):
        c_reader, c_writer, s_reader, s_writer, server = await _socket_pair()
        try:
            await write_frame(c_writer, {"t": "ping"})
            assert await read_frame(s_reader) == {"t": "ping"}
            await write_frame(s_writer, {"t": "pong"})
            assert await read_frame(c_reader) == {"t": "pong"}
        finally:
            await _close(c_writer, s_writer, server)

    async def test_non_serialisable_value_is_stringified_on_the_wire(self):
        c_reader, c_writer, s_reader, s_writer, server = await _socket_pair()
        try:
            from datetime import datetime

            ts = datetime(2026, 6, 5, 7, 8, 9)
            await write_frame(c_writer, {"t": "event", "ts": ts})
            frame = await read_frame(s_reader)
            assert frame == {"t": "event", "ts": str(ts)}
        finally:
            await _close(c_writer, s_writer, server)

    async def test_reader_sees_eof_as_none(self):
        c_reader, c_writer, s_reader, s_writer, server = await _socket_pair()
        try:
            c_writer.close()
            await c_writer.wait_closed()
            assert await read_frame(s_reader) is None
        finally:
            await _close(s_writer, server)

    async def test_concatenated_frames_in_one_write_are_split(self):
        """A single write carrying several frames is still read one-by-one."""
        c_reader, c_writer, s_reader, s_writer, server = await _socket_pair()
        try:
            c_writer.write(b'{"a": 1}\n{"b": 2}\n{"c": 3}\n')
            await c_writer.drain()
            c_writer.write_eof()
            received = [f async for f in iter_frames(s_reader)]
            assert received == [{"a": 1}, {"b": 2}, {"c": 3}]
        finally:
            await _close(c_writer, s_writer, server)
