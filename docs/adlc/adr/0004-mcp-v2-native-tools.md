# ADR 0004: MCP 2.0 behind a native tool gateway

Status: accepted.

Decision: use MCP 2.0, explicit server configuration, per-tool allowlists,
namespaced `StructuredTool` adapters, scope checks, and bounded calls. Use native
LangChain `@tool` for project-owned model affordances. Do not monkey-patch.

Consequences: LangSmith receives standard tool spans. MCP is advisory by
default and cannot expose raw financial execution.
