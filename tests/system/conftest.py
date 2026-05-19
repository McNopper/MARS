"""System tier — full-stack end-to-end tests.

Contract
--------
* Starts real server subprocesses and/or calls real external APIs.
* Slow by design — heavy LLM tests are excluded from the default run.
* Only reached when all unit, component, and module tests pass.

Excluded from default run (require explicit opt-in):
* test_ollama_service.py  — requires a running Ollama instance
* test_anthropic_agent_credit_free.py  — makes real Anthropic API calls
"""
