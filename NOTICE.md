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
- Two-level directory hierarchy: Domain Directory (DIDF) / Global Directory (DSDF) (→ `Directory` + `DomainDirectory`)
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
- Capability-based discovery across heterogeneous data sources (→ `Directory.find_by_capability`)

### [5] Patient Technology for Impatiently Patients
**R. Müller, N. Nopper, et al., ~2003**  
`papers/Patient_Technology_for_Impatiently_Patients.pdf`

Concepts used in MARS:
- Explicit governance rule framework (*Regelrahmen*) for self-organizing agent systems (→ `PolicyEngine`)
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

### Optional provider SDK dependencies (installed separately)

| Library | License | Source |
|---------|---------|--------|
| anthropic | MIT | <https://github.com/anthropics/anthropic-sdk-python> |
| google-genai | Apache 2.0 | <https://github.com/googleapis/python-genai> |
| cohere | MIT | <https://github.com/cohere-ai/cohere-python> |
| boto3 | Apache 2.0 | <https://github.com/boto/boto3> |
| groq | Apache 2.0 | <https://github.com/groq/groq-python> |
| mistralai | Apache 2.0 | <https://github.com/mistralai/client-python> |

---

## Third-Party LLM Provider Services – Terms of Service

MARS provides adapter code to connect to external LLM APIs. Use of these services is subject to each provider's own Terms of Service, Privacy Policy, and Acceptable Use Policy. Users are responsible for:

- Obtaining and securing their own API credentials
- Complying with each provider's usage restrictions and rate limits
- Ensuring that data sent to external APIs meets their data-handling requirements (including GDPR, HIPAA, or other applicable regulations)

### Provider Terms of Service (as of 2026)

| Provider | Terms of Service |
|----------|-----------------|
| OpenAI | <https://openai.com/policies/terms-of-use> |
| Anthropic | <https://www.anthropic.com/legal/consumer-terms> |
| Google Gemini | <https://ai.google.dev/gemini-api/terms> |
| Groq | <https://groq.com/terms-of-service/> |
| Mistral AI | <https://mistral.ai/terms/> |
| xAI / Grok | <https://x.ai/legal/terms-of-service> |
| DeepSeek | <https://www.deepseek.com/terms> |
| Perplexity AI | <https://www.perplexity.ai/hub/legal/terms-of-service> |
| Together AI | <https://www.together.ai/terms-of-service> |
| Fireworks AI | <https://fireworks.ai/terms-of-service> |
| Cerebras | <https://cloud.cerebras.ai/terms> |
| NVIDIA NIM | <https://www.nvidia.com/en-us/agreements/cloud-terms-of-service/> |
| OpenRouter | <https://openrouter.ai/terms> |
| Cloudflare AI | <https://www.cloudflare.com/website-terms/> |
| HuggingFace | <https://huggingface.co/terms-of-service> |
| AWS Bedrock | <https://aws.amazon.com/service-terms/> |
| Azure OpenAI | <https://azure.microsoft.com/en-us/support/legal/> |

> Local providers (Ollama, LM Studio) run entirely on your own hardware and send no data to external servers.

---

## Artifact Exchange

MARS supports inter-agent artifact exchange (binary files, archives, etc.). Artifacts are stored in-process in the `ArtifactStore` (`mars/artifacts/`). No artifact data is transmitted to external services unless an `LLMAgent` explicitly sends artifact content to an LLM API as part of a conversation. Users are responsible for ensuring that artifact content complies with applicable provider Terms of Service when including it in LLM prompts.
