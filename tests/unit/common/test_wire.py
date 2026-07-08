"""Unit tests for the shared newline-delimited JSON wire framing helpers."""

from __future__ import annotations

import asyncio
import json

import pytest

from mars.common.wire import (
    decode_frame,
    encode_frame,
    iter_frames,
    read_frame,
    write_frame,
)


# ---------------------------------------------------------------------------
# encode_frame
# ---------------------------------------------------------------------------

class TestEncodeFrame:
    def test_appends_single_newline_and_utf8_encodes(self):
        out = encode_frame({"t": "msg", "text": "hi"})
        assert isinstance(out, bytes)
        assert out.endswith(b"\n")
        assert out.count(b"\n") == 1
        assert json.loads(out.decode("utf-8")) == {"t": "msg", "text": "hi"}

    def test_non_ascii_is_preserved_as_utf8(self):
        out = encode_frame({"text": "✓ café"})
        assert json.loads(out.decode("utf-8"))["text"] == "✓ café"

    def test_default_stringifies_non_serialisable_values(self):
        class Weird:
            def __str__(self) -> str:
                return "weird-value"

        out = encode_frame({"v": Weird()})
        assert json.loads(out.decode("utf-8"))["v"] == "weird-value"

    def test_default_none_raises_on_non_serialisable(self):
        with pytest.raises(TypeError):
            encode_frame({"v": object()}, default=None)

    def test_round_trips_with_decode_frame(self):
        payload = {"t": "artifact", "name": "x.json", "nums": [1, 2, 3]}
        assert decode_frame(encode_frame(payload)) == payload


# ---------------------------------------------------------------------------
# decode_frame
# ---------------------------------------------------------------------------

class TestDecodeFrame:
    def test_decodes_bytes(self):
        assert decode_frame(b'{"a": 1}\n') == {"a": 1}

    def test_decodes_str(self):
        assert decode_frame('{"a": 1}') == {"a": 1}

    def test_strips_surrounding_whitespace_and_newlines(self):
        assert decode_frame(b'  {"a": 1}  \n') == {"a": 1}

    @pytest.mark.parametrize("raw", [b"", b"   ", b"\n", "", "   "])
    def test_empty_or_blank_returns_none(self, raw):
        assert decode_frame(raw) is None

    def test_malformed_json_returns_none(self):
        assert decode_frame(b"{not json") is None

    def test_invalid_utf8_returns_none(self):
        assert decode_frame(b"\xff\xfe") is None

    def test_non_object_returns_none_by_default(self):
        assert decode_frame(b"[1, 2, 3]") is None
        assert decode_frame(b"42") is None

    def test_non_object_allowed_when_require_dict_false(self):
        assert decode_frame(b"[1, 2, 3]", require_dict=False) == [1, 2, 3]
        assert decode_frame(b"42", require_dict=False) == 42


# ---------------------------------------------------------------------------
# write_frame  (against a real asyncio StreamWriter)
# ---------------------------------------------------------------------------

class _FakeTransport(asyncio.Transport):
    def __init__(self) -> None:
        super().__init__()
        self.buffer = bytearray()
        self._closing = False

    def write(self, data) -> None:  # type: ignore[override]
        self.buffer.extend(data)

    def is_closing(self) -> bool:  # type: ignore[override]
        return self._closing

    def close(self) -> None:  # type: ignore[override]
        self._closing = True


def _make_writer(transport: _FakeTransport) -> asyncio.StreamWriter:
    loop = asyncio.get_event_loop()
    reader = asyncio.StreamReader()
    protocol = asyncio.StreamReaderProtocol(reader)
    return asyncio.StreamWriter(transport, protocol, reader, loop)


class TestWriteFrame:
    @pytest.mark.asyncio
    async def test_writes_one_frame_and_returns_true(self):
        transport = _FakeTransport()
        writer = _make_writer(transport)
        ok = await write_frame(writer, {"t": "msg"})
        assert ok is True
        assert bytes(transport.buffer) == b'{"t": "msg"}\n'

    @pytest.mark.asyncio
    async def test_returns_false_when_writer_closing_and_writes_nothing(self):
        transport = _FakeTransport()
        writer = _make_writer(transport)
        transport.close()
        ok = await write_frame(writer, {"t": "msg"})
        assert ok is False
        assert bytes(transport.buffer) == b""


# ---------------------------------------------------------------------------
# read_frame / iter_frames  (against a fed StreamReader)
# ---------------------------------------------------------------------------

def _reader_from(data: bytes) -> asyncio.StreamReader:
    reader = asyncio.StreamReader()
    reader.feed_data(data)
    reader.feed_eof()
    return reader


class TestReadFrame:
    @pytest.mark.asyncio
    async def test_reads_successive_frames(self):
        reader = _reader_from(b'{"a": 1}\n{"b": 2}\n')
        assert await read_frame(reader) == {"a": 1}
        assert await read_frame(reader) == {"b": 2}

    @pytest.mark.asyncio
    async def test_returns_none_at_eof(self):
        reader = _reader_from(b"")
        assert await read_frame(reader) is None

    @pytest.mark.asyncio
    async def test_skips_blank_and_malformed_lines(self):
        reader = _reader_from(b'\n{bad json\n{"ok": true}\n')
        assert await read_frame(reader) == {"ok": True}

    @pytest.mark.asyncio
    async def test_returns_none_when_only_garbage(self):
        reader = _reader_from(b"{bad\n{also bad\n")
        assert await read_frame(reader) is None


class TestIterFrames:
    @pytest.mark.asyncio
    async def test_yields_all_valid_frames_until_eof(self):
        reader = _reader_from(b'{"a": 1}\n{bad\n{"b": 2}\n\n{"c": 3}\n')
        frames = [f async for f in iter_frames(reader)]
        assert frames == [{"a": 1}, {"b": 2}, {"c": 3}]

    @pytest.mark.asyncio
    async def test_empty_stream_yields_nothing(self):
        reader = _reader_from(b"")
        frames = [f async for f in iter_frames(reader)]
        assert frames == []
