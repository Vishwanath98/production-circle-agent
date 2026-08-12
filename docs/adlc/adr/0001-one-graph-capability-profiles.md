# ADR 0001: One graph with capability profiles

Status: accepted for the local lab.

Decision: maintain one Circle LangGraph and select provider/RAG/MCP/x402 through
server-owned profiles. Legacy base/RAG/MCP modules are compatibility references,
not implementation templates.

Consequences: security and state behavior cannot drift by variant; every
profile runs the same authorization, policy, HITL, persistence, and audit code.
Profile tests must prove tool exposure and provider choice.
