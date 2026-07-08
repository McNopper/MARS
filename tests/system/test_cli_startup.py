"""Smoke tests: verify mars.cli.main imports cleanly and can be invoked."""
from __future__ import annotations

import importlib
import subprocess
import sys


class TestCLIImports:
    """All cli sub-modules must be importable without side-effects."""

    def _import(self, module: str) -> None:
        importlib.import_module(module)

    def test_import_cli_main(self) -> None:
        self._import("mars.cli.main")

    def test_import_cli_models(self) -> None:
        self._import("mars.common.models")

    def test_import_cli_utils(self) -> None:
        self._import("mars.cli.utils")

    def test_import_cli_service_manager(self) -> None:
        self._import("mars.server.service_manager")

    def test_import_cli_renderer(self) -> None:
        self._import("mars.cli.renderer")

    def test_import_cli_client(self) -> None:
        self._import("mars.cli.client")

    def test_no_github_models_import(self) -> None:
        """Verify the removed provider is not imported anywhere in cli modules."""
        for mod_name in [
            "mars.cli.main",
            "mars.cli.client",
        ]:
            mod = importlib.import_module(mod_name)
            src_file = getattr(mod, "__file__", "") or ""
            if src_file:
                content = open(src_file, encoding="utf-8").read()
                assert "github_models" not in content, (
                    f"{mod_name} still references the removed github_models module"
                )


class TestCLIHelpFlag:
    """Running the CLI with --help must exit 0 and print usage."""

    def test_help_exits_zero(self) -> None:
        result = subprocess.run(
            [sys.executable, "-m", "mars.cli.main", "--help"],
            capture_output=True,
            text=True,
            timeout=15,
        )
        assert result.returncode == 0

    def test_help_shows_usage(self) -> None:
        result = subprocess.run(
            [sys.executable, "-m", "mars.cli.main", "--help"],
            capture_output=True,
            text=True,
            timeout=15,
        )
        assert "usage" in result.stdout.lower() or "mars" in result.stdout.lower()

    def test_help_lists_provider_option(self) -> None:
        result = subprocess.run(
            [sys.executable, "-m", "mars.cli.main", "--help"],
            capture_output=True,
            text=True,
            timeout=15,
        )
        assert "--provider" in result.stdout

    def test_help_lists_model_option(self) -> None:
        result = subprocess.run(
            [sys.executable, "-m", "mars.cli.main", "--help"],
            capture_output=True,
            text=True,
            timeout=15,
        )
        assert "--model" in result.stdout
