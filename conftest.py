"""Root pytest configuration.

Sound tests (marked with @pytest.mark.sound) are skipped by default.
Run them explicitly with:  pytest --run-sound
or set the environment variable:  RUN_SOUND_TESTS=1
"""
import os
import pytest


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--run-sound",
        action="store_true",
        default=False,
        help="Run tests that produce actual audio output (skipped by default).",
    )


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    run_sound = config.getoption("--run-sound") or os.environ.get("RUN_SOUND_TESTS", "").lower() in ("1", "true", "yes")
    if not run_sound:
        skip_sound = pytest.mark.skip(reason="Audio output test — run with --run-sound or RUN_SOUND_TESTS=1")
        for item in items:
            if item.get_closest_marker("sound"):
                item.add_marker(skip_sound)
