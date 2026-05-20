"""Unit tests for mars.runtime.agents.clock_agent."""
from __future__ import annotations

import urllib.error

import pytest

from mars.runtime.agents import clock_agent


class TestBuildSnapshot:
    def test_required_keys_present(self) -> None:
        geo = {
            "ip": "1.2.3.4", "city": "Berlin", "country": "Germany",
            "country_code": "DE", "lat": 52.5, "lon": 13.4,
            "timezone": "Europe/Berlin", "isp": "Acme", "geo_source": "ip-api.com",
        }
        snap = clock_agent._build_snapshot(geo)
        for key in ("timestamp", "local_time", "local_date", "utc_offset"):
            assert key in snap, f"missing key: {key}"

    def test_geo_fields_merged(self) -> None:
        geo = {"ip": "9.9.9.9", "city": "Tokyo", "country": "Japan",
               "country_code": "JP", "lat": 35.7, "lon": 139.7,
               "timezone": "Asia/Tokyo", "isp": "ISP", "geo_source": "ip-api.com"}
        snap = clock_agent._build_snapshot(geo)
        assert snap["city"] == "Tokyo"
        assert snap["country"] == "Japan"
        assert snap["ip"] == "9.9.9.9"

    def test_utc_offset_format(self) -> None:
        geo = {"ip": None, "city": None, "country": None, "country_code": None,
               "lat": None, "lon": None, "timezone": None, "isp": None,
               "geo_source": "offline"}
        snap = clock_agent._build_snapshot(geo)
        # Must be ±HH:MM
        assert snap["utc_offset"][0] in ("+", "-")
        parts = snap["utc_offset"][1:].split(":")
        assert len(parts) == 2
        assert all(p.isdigit() for p in parts)

    def test_timestamp_is_iso8601(self) -> None:
        geo = {"ip": None, "city": None, "country": None, "country_code": None,
               "lat": None, "lon": None, "timezone": None, "isp": None,
               "geo_source": "offline"}
        snap = clock_agent._build_snapshot(geo)
        from datetime import datetime
        # Should parse without error
        dt = datetime.fromisoformat(snap["timestamp"].replace("Z", "+00:00"))
        assert dt is not None


class TestFetchGeo:
    def test_returns_offline_on_network_failure(self, monkeypatch) -> None:
        def _raise(url, timeout=None):  # noqa: ARG001
            raise OSError("no network")

        monkeypatch.setattr(clock_agent.urllib.request, "urlopen", _raise)
        result = clock_agent._fetch_geo()
        assert result["geo_source"] == "offline"
        assert result["ip"] is None
        assert result["city"] is None

    def test_primary_source_used_on_success(self, monkeypatch) -> None:
        import io

        class _FakeResponse:
            def __init__(self, data: bytes) -> None:
                self._data = data

            def read(self) -> bytes:
                return self._data

            def __enter__(self):
                return self

            def __exit__(self, *_):
                pass

        import json
        payload = json.dumps({
            "status": "success", "query": "5.5.5.5", "city": "Paris",
            "country": "France", "countryCode": "FR", "lat": 48.8, "lon": 2.3,
            "timezone": "Europe/Paris", "isp": "Orange",
        }).encode()

        monkeypatch.setattr(
            clock_agent.urllib.request, "urlopen",
            lambda url, timeout=None: _FakeResponse(payload),
        )
        result = clock_agent._fetch_geo()
        assert result["geo_source"] == "ip-api.com"
        assert result["city"] == "Paris"
        assert result["ip"] == "5.5.5.5"
