# NOTICE

**MARS – Multi-Agent Runtime System**  
Copyright (c) 2026 Norbert Nopper  
Licensed under the MIT License (see [LICENSE](LICENSE)).

---

## Research Foundation

MARS is grounded in peer-reviewed research and a patent authored or co-authored by Norbert Nopper. The following works are included in the `papers/` directory (stored via Git LFS) as the conceptual and architectural basis of this implementation. All concepts are used with the full right of the original author.

### [1] AgentLink – A Living Agents Runtime System (LARS)
**N. Nopper, 2000**  
`papers/AgentLink_living_agents_runtime_system.pdf`

Concepts used in MARS:
- Thread-per-agent execution model (→ `asyncio.Task` per agent)
- Agent Management System (AMS) with lifecycle state machine (`INITIALIZING → ACTIVE → SUSPENDED → TERMINATED`)
- ACL-inspired inter-agent message passing with performatives
- SSL-secured agent transport (→ HTTPS / TLS on provider APIs)
- Agent clustering and mobility across runtime nodes

### [2] Agent-Based Counterparty Matching in Agent-Based Trading
**M. Lohmann, N. Nopper, C. Henning, 1998**  
`papers/Agent-Based_Counterparty_Matching_in_Agent-Based_Trading.pdf`

Concepts used in MARS:
- Two-level directory hierarchy: Domain Directory (DIDF) / Global Directory (DSDF) (→ skill-routing index in `mars/runtime/server/`)
- Specialist agents operating over a shared runtime platform

### [3] EMIKA – System Architecture and Prototypic Realization
**R. Müller, T. Eymann, N. Nopper, et al., 2004**  
`papers/EMIKA_System_Architecture_and_Prototypic_Realization.pdf`

Concepts used in MARS:
- Real-time sensor-to-agent middleware layer
- Ist/Soll-Zustand (actual/target state) comparison per agent
- Self-organizing multi-agent coordination in resource-constrained environments (→ hospital, IoT, edge deployments)

### [4] Method, Computer and Computer Program Product for Access to Location Dependent Data
**N. Nopper, M. Kammerer — European Patent Application, 2000**  
`papers/Method_computer_and_computer_program_product_for_access_to_location_dependent_data.pdf`

Concepts used in MARS:
- Context-threaded, federated multi-source agent retrieval
- Capability-based discovery across heterogeneous data sources (→ `ScopeStore.find_by_skill()`)

### [5] Patient Technology for Impatiently Patients
**R. Müller, N. Nopper, et al., ~2003**  
`papers/Patient_Technology_for_Impatiently_Patients.pdf`

Concepts used in MARS:
- Explicit governance rule framework (*Regelrahmen*) for self-organizing agent systems (→ planned future feature)
- Rule-chain architecture: logging → rate-limiting → capability-check → custom policies

---

## Third-Party Software

MARS depends on the following open-source libraries.

| Library | Version | License | Source |
|---------|---------|---------|--------|
| openai | ≥1.30 | MIT | <https://github.com/openai/openai-python> |
| httpx | ≥0.27 | BSD 3-Clause | <https://github.com/encode/httpx> |
| pydantic | ≥2.7 | MIT | <https://github.com/pydantic/pydantic> |
| rich | ≥13.0 | MIT | <https://github.com/Textualize/rich> |
| Pillow | ≥10.0 | HPND | <https://github.com/python-pillow/Pillow> |

### Optional provider SDK dependencies (installed separately)

| Library | License | Source |
|---------|---------|--------|
| anthropic | MIT | <https://github.com/anthropics/anthropic-sdk-python> |

---

## Third-Party LLM Provider Services – Terms of Service

MARS provides adapter code to connect to external LLM APIs. Use of these services is subject to each provider's own Terms of Service, Privacy Policy, and Acceptable Use Policy. Users are responsible for:

- Obtaining and securing their own API credentials
- Complying with each provider's usage restrictions and rate limits
- Ensuring that data sent to external APIs meets their data-handling requirements (including GDPR, HIPAA, or other applicable regulations)

### Provider Terms of Service (as of 2026)

| Provider | Terms of Service |
|----------|-----------------|
| Anthropic | <https://www.anthropic.com/legal/consumer-terms> |
| GitHub Copilot | <https://docs.github.com/en/site-policy/github-terms/github-terms-for-additional-products-and-features#github-copilot> |

> Local providers (Ollama) run entirely on your own hardware and send no data to external servers.

---

## Artifact Exchange

MARS supports inter-agent artifact exchange (binary files, archives, etc.). Artifacts are stored in-process in the `ArtifactStore` (`mars/storage/artifacts/`). No artifact data is transmitted to external services unless an `LLMAgent` explicitly sends artifact content to an LLM API as part of a conversation. Users are responsible for ensuring that artifact content complies with applicable provider Terms of Service when including it in LLM prompts.
