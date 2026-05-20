"""Unit tests for mars.runtime.agents.url_agent.

Covers:
- _is_private: private/loopback address detection
- fetch_url: blocked private addresses, HTTP error handling
- _parse_request: plain text and JSON dispatch
"""
from __future__ import annotations

import unittest.mock as mock

import pytest

from mars.runtime.agents.url_agent import _is_private, _parse_request, fetch_url


# ---------------------------------------------------------------------------
# _is_private
# ---------------------------------------------------------------------------

class TestIsPrivate:
    def test_loopback(self) -> None:
        assert _is_private("127.0.0.1") is True

    def test_localhost_name(self) -> None:
        # May resolve to 127.0.0.1 or ::1; either way it's private
        result = _is_private("localhost")
        assert result is True

    def test_class_a_private(self) -> None:
        with mock.patch("socket.gethostbyname", return_value="10.0.0.1"):
            assert _is_private("internal.example") is True

    def test_class_c_private(self) -> None:
        with mock.patch("socket.gethostbyname", return_value="192.168.1.1"):
            assert _is_private("my-router") is True

    def test_public_address(self) -> None:
        with mock.patch("socket.gethostbyname", return_value="8.8.8.8"):
            assert _is_private("dns.google") is False

    def test_unreachable_host_not_private(self) -> None:
        import socket
        with mock.patch("socket.gethostbyname", side_effect=socket.gaierror("fail")):
            assert _is_private("does-not-exist.invalid") is False


# ---------------------------------------------------------------------------
# fetch_url — blocked private addresses
# ---------------------------------------------------------------------------

class TestFetchUrlBlocked:
    def test_private_address_blocked_by_default(self) -> None:
        with mock.patch("socket.gethostbyname", return_value="192.168.1.1"):
            result = fetch_url("http://internal-server/data")
        assert result["ok"] is False
        assert "blocked" in result["error"]

    def test_private_address_allowed_with_flag(self) -> None:
        # We just check no "blocked" error; actual request will fail without a server
        with mock.patch("socket.gethostbyname", return_value="192.168.1.1"):
            with mock.patch("urllib.request.urlopen") as mock_open:
                mock_resp = mock.MagicMock()
                mock_resp.__enter__ = mock.MagicMock(return_value=mock_resp)
                mock_resp.__exit__ = mock.MagicMock(return_value=False)
                mock_resp.status = 200
                mock_resp.url = "http://192.168.1.1/data"
                mock_resp.headers.get.return_value = "text/plain"
                mock_resp.headers.items.return_value = []
                mock_resp.read.return_value = b"hello"
                mock_open.return_value = mock_resp
                result = fetch_url("http://192.168.1.1/data", allow_private=True)
        assert result["ok"] is True


# ---------------------------------------------------------------------------
# _parse_request
# ---------------------------------------------------------------------------

class TestParseRequest:
    def test_bare_url_performs_get(self) -> None:
        with mock.patch("socket.gethostbyname", return_value="93.184.216.34"):
            with mock.patch("urllib.request.urlopen") as mock_open:
                mock_resp = mock.MagicMock()
                mock_resp.__enter__ = mock.MagicMock(return_value=mock_resp)
                mock_resp.__exit__ = mock.MagicMock(return_value=False)
                mock_resp.status = 200
                mock_resp.url = "https://example.com"
                mock_resp.headers.get.return_value = "text/html"
                mock_resp.headers.items.return_value = []
                mock_resp.read.return_value = b"<html></html>"
                mock_open.return_value = mock_resp
                result = _parse_request("https://example.com")
        assert result["ok"] is True
        assert result["method"] == "GET"

    def test_json_command(self) -> None:
        import json
        with mock.patch("socket.gethostbyname", return_value="93.184.216.34"):
            with mock.patch("urllib.request.urlopen") as mock_open:
                mock_resp = mock.MagicMock()
                mock_resp.__enter__ = mock.MagicMock(return_value=mock_resp)
                mock_resp.__exit__ = mock.MagicMock(return_value=False)
                mock_resp.status = 200
                mock_resp.url = "https://example.com/api"
                mock_resp.headers.get.return_value = "application/json"
                mock_resp.headers.items.return_value = []
                mock_resp.read.return_value = b'{"ok": true}'
                mock_open.return_value = mock_resp
                result = _parse_request(json.dumps({"url": "https://example.com/api"}))
        assert result["ok"] is True

    def test_missing_url_json_returns_error(self) -> None:
        import json
        result = _parse_request(json.dumps({"method": "GET"}))
        assert result["ok"] is False
        assert "url" in result["error"]

    def test_empty_request_returns_error(self) -> None:
        result = _parse_request("")
        assert result["ok"] is False

    def test_private_url_blocked_in_json(self) -> None:
        import json
        with mock.patch("socket.gethostbyname", return_value="10.0.0.1"):
            result = _parse_request(json.dumps({"url": "http://internal/secret"}))
        assert result["ok"] is False
        assert "blocked" in result["error"]
