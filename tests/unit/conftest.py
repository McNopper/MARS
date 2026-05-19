"""Unit tier — isolated single-unit tests.

Contract
--------
* One class or function under test; all external dependencies are mocked.
* No real network connections, no subprocesses, no disk I/O beyond tmp_path.
* Each test must complete in milliseconds.
* If any test here fails, the component/module/system tiers do not run.
"""
