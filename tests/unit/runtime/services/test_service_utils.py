"""Unit tests for mars.runtime.services.service_utils."""
from __future__ import annotations

import base64
import json

import pytest

from mars.runtime.services.service_utils import (
    build_hello,
    decode_base64_bytes,
    encode_json_artifact,
    extract_payload_attachment,
    guess_extension,
    has_module,
    is_target_message,
    looks_like_base64,
    parse_server,
    split_data_uri,
)


# ---------------------------------------------------------------------------
# parse_server
# ---------------------------------------------------------------------------

class TestParseServer:
    def test_host_and_port_split(self):
        assert parse_server("localhost:7432") == ("localhost", 7432)

    def test_ipv4_and_port(self):
        assert parse_server("192.168.1.1:9000") == ("192.168.1.1", 9000)

    def test_port_only_defaults_host_to_localhost(self):
        host, port = parse_server(":7432")
        assert port == 7432

    def test_non_numeric_port_falls_back_to_default(self):
        _, port = parse_server("localhost:abc")
        assert port == 7432


# ---------------------------------------------------------------------------
# build_hello
# ---------------------------------------------------------------------------

class TestBuildHello:
    def test_returns_hello_payload(self):
        h = build_hello("svc.test", ["skill_a", "skill_b"])
        assert h["t"] == "hello"
        assert h["name"] == "svc.test"
        assert h["skills"] == ["skill_a", "skill_b"]


# ---------------------------------------------------------------------------
# encode_json_artifact / decode_base64_bytes
# ---------------------------------------------------------------------------

class TestEncodeDecodeArtifact:
    def test_roundtrip(self):
        obj = {"key": "value", "num": 42}
        encoded = encode_json_artifact(obj)
        raw = base64.b64decode(encoded)
        decoded = json.loads(raw)
        assert decoded == obj

    def test_result_is_ascii(self):
        encoded = encode_json_artifact({"x": 1})
        assert encoded.isascii()

    def test_decode_base64_bytes_roundtrip(self):
        data = b"\x89PNG\r\n\x1a\n"
        b64 = base64.b64encode(data).decode()
        assert decode_base64_bytes(b64) == data


# ---------------------------------------------------------------------------
# looks_like_base64
# ---------------------------------------------------------------------------

class TestLooksLikeBase64:
    def test_valid_base64_recognised(self):
        data = base64.b64encode(b"x" * 64).decode()
        assert looks_like_base64(data)

    def test_short_string_rejected(self):
        assert not looks_like_base64("abc=")

    def test_plain_text_rejected(self):
        assert not looks_like_base64("hello world, this is a plain text sentence that is long enough")


# ---------------------------------------------------------------------------
# split_data_uri
# ---------------------------------------------------------------------------

class TestSplitDataUri:
    def test_valid_data_uri(self):
        uri = "data:image/png;base64,abc123"
        mime, data = split_data_uri(uri)
        assert mime == "image/png"
        assert data == "abc123"

    def test_plain_string_returns_none_mime(self):
        mime, data = split_data_uri("not-a-data-uri")
        assert mime is None
        assert data == "not-a-data-uri"


# ---------------------------------------------------------------------------
# is_target_message
# ---------------------------------------------------------------------------

class TestIsTargetMessage:
    def test_matching_msg_returns_true(self):
        ev = {"t": "msg", "target": "svc.clock@1"}
        assert is_target_message(ev, "svc.clock@1")

    def test_wrong_target_returns_false(self):
        ev = {"t": "msg", "target": "svc.other@1"}
        assert not is_target_message(ev, "svc.clock@1")

    def test_non_msg_type_returns_false(self):
        ev = {"t": "hello", "target": "svc.clock@1"}
        assert not is_target_message(ev, "svc.clock@1")


# ---------------------------------------------------------------------------
# has_module
# ---------------------------------------------------------------------------

class TestHasModule:
    def test_stdlib_module_found(self):
        assert has_module("json")

    def test_nonexistent_module_not_found(self):
        assert not has_module("_this_package_does_not_exist_xyz")


# ---------------------------------------------------------------------------
# guess_extension
# ---------------------------------------------------------------------------

class TestGuessExtension:
    def test_png_by_header(self):
        assert guess_extension(b"\x89PNG\r\n\x1a\n", None, fallback=".bin") == ".png"

    def test_jpeg_by_header(self):
        assert guess_extension(b"\xff\xd8\xff", None, fallback=".bin") == ".jpg"

    def test_png_by_mime(self):
        assert guess_extension(b"", "image/png", fallback=".bin") == ".png"

    def test_fallback_for_unknown(self):
        assert guess_extension(b"\x00\x00", None, fallback=".dat") == ".dat"
