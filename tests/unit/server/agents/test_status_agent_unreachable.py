"""Unit tests for the status agent's REST-unreachable handling.

When mars-server's REST API is down (e.g. running CLI standalone, or before
REST has bound its port), the status agent must NOT leak raw urlopen/WinError
text into the artifact. Instead it returns a clean, actionable diagnostic.
"""
from __future__ import annotations

import urllib.error


from mars.server.services.builtin import status


class TestRestUnreachable:
    def test_http_get_json_translates_connection_refused(self, monkeypatch) -> None:
        def _raise(_url, timeout=None):  # noqa: ARG001
            raise urllib.error.URLError(
                "<urlopen error [WinError 10061] Es konnte keine Verbindung "
                "hergestellt werden, da der Zielcomputer die Verbindung verweigerte>"
            )

        monkeypatch.setattr(status.urllib.request, "urlopen", _raise)
        result = status._http_get_json("http://localhost:7433/agents")
        assert isinstance(result, dict)
        assert result.get("error") == "rest_unreachable"
        assert "not reachable" in result.get("message", "")
        assert "10061" not in result.get("message", "")

    def test_collect_status_collapses_to_top_level_diagnostic(self, monkeypatch) -> None:
        def _raise(_url, timeout=None):  # noqa: ARG001
            raise ConnectionRefusedError(10061, "actively refused")

        monkeypatch.setattr(status.urllib.request, "urlopen", _raise)
        snap = status.collect_status("http://localhost:7433")
        assert snap.get("status") == "rest_unreachable"
        assert "not reachable" in snap.get("message", "")
        # The noisy per-endpoint copies should be gone
        assert "agents" not in snap
        assert "scopes" not in snap
        assert "problems" not in snap

    def test_generic_http_error_passes_through(self, monkeypatch) -> None:
        def _raise(_url, timeout=None):  # noqa: ARG001
            raise ValueError("not valid json")

        monkeypatch.setattr(status.urllib.request, "urlopen", _raise)
        result = status._http_get_json("http://localhost:7433/agents")
        assert isinstance(result, dict)
        assert result.get("error", "").startswith("ValueError")
