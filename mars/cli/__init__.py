"""MARS CLI – interactive command-line interface.

Usage::

    mars                          # start interactive REPL
    mars --provider ollama        # start with specific provider
    mars --provider openai --model gpt-4o

See ``mars --help`` for full options.
"""

from mars.cli.main import main

__all__ = ["main"]
