"""Module tier — full-feature in-process tests.

Contract
--------
* A complete feature tested end-to-end inside one process.
* May open real loopback TCP connections or touch the filesystem.
* No external services (no Ollama, no cloud APIs).
* If any test here fails, the system tier does not run.
"""
