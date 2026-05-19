"""Component tier — cross-module wiring tests.

Contract
--------
* A handful of units wired together inside one process.
* Checks that modules import cleanly and that classes integrate correctly.
* No real network I/O, no subprocesses.
* If any test here fails, the module/system tiers do not run.
"""
