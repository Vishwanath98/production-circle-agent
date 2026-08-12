# Coding-agent build map

## Shared foundation

| Concern | Primary file | Contract |
|---|---|---|
| Principal and credentials | `agent-spine/agent_spine/auth.py` | Hashed opaque tokens, expiration, revocation, roles and scopes |
| Runtime identity | `agent-spine/agent_spine/context.py` | Server-created context injected through `RunnableConfig` |
| Durable data | `agent-spine/agent_spine/store.py` | SQLite WAL, composite tenant keys, transactional claims |
| Action envelope | `agent-spine/agent_spine/actions.py` | Canonical arguments, redaction, digest, idempotency |
| Policy | `agent-spine/agent_spine/policy.py` | Three outcomes; all transfers require reviewer/admin |
| Approval | `agent-spine/agent_spine/approvals.py` | Exact digest, expiry, role/scope, one decision per reviewer |
| Checkpointing | `agent-spine/agent_spine/checkpointer.py` | Durable by default; no silent in-memory downgrade |
| Tool registry | `agent-spine/agent_spine/tool_catalog.py` | Every model tool is a `BaseTool` with effect/risk/permission metadata |
| MCP gateway | `agent-spine/agent_spine/mcp_gateway.py` | Explicit servers and allowlists; namespaced `StructuredTool` adapters |

## Circle implementation

| Concern | Primary file | Contract |
|---|---|---|
| Unified graph | `circle-agent/circle_agent/agent.py` | One graph, multi-turn checkpoint, interrupt/resume |
| Native tools | `circle-agent/circle_agent/tools.py` | `@tool`; runtime config hidden; raw executor is not a tool |
| Service boundary | `circle-agent/circle_agent/service.py` | Validate, quote, screen, decide, persist, execute |
| Simulator | `circle-agent/circle_agent/simulator.py` | Deterministic, DB-backed, no live fallback |
| Circle SDK | `circle-agent/circle_agent/circle_provider.py` | Official SDK 9.6, testnet only, UUIDv4 idempotency |
| RAG | `circle-agent/circle_agent/rag_service.py` | SQL tenant prefilter before similarity scoring |
| x402 | `circle-agent/circle_agent/x402_provider.py` | Testnet requirements mapped into the standard transfer action |
| Webhooks | `circle-agent/circle_agent/webhooks.py` | ECDSA verification, subscription-to-tenant map, dedupe |
| HTTP/API | `circle-agent/circle_agent/api.py` | Same execution path for console, native REST, `/chat`, OpenAI shape |
| Local console | `circle-agent/ui/` | Auth, profiles, threads, chat, approval inbox |

## Rules for future coding agents

- Never add a second transfer executor. Only `transfer_execute()` may cross the
  financial effect boundary.
- Never expose `transfer_execute()` as a model tool or MCP tool.
- Never accept `organization_id`, roles, scopes, approval state, or runtime
  context from model arguments.
- Never query a multi-tenant table by object ID alone.
- Never perform vector search before the SQL tenant/visibility filter.
- Never silently replace Circle with simulation or durable state with memory.
- Add new capabilities through profile metadata and the tool catalog, not by
  copying the graph.
- Add a deny/cross-tenant/replay test before adding an allow-path test.
