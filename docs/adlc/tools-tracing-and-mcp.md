# Tools, tracing, and MCP

## Where `@tool` belongs

Use native `@tool` on functions the model may intentionally call:

- policy search;
- wallet balance;
- transfer quote;
- transaction status;
- transfer request;
- x402 requirement inspection and payment request.

Do not decorate graph nodes, routers, parsers, policy evaluation, approval
decision code, persistence, provider clients, webhook processors, or
`transfer_execute()`. Those are implementation spans, not model affordances.
Decorating them would both pollute the model schema and risk exposing privileged
operations.

LangChain-native tools emit tool runs to LangSmith without the old
`traceable(...)(fn)` patch. Runtime `config` carries LangSmith metadata but is
hidden from the tool input schema. Provider/policy/approval spans should use
normal LangSmith runnables or explicit tracing at stable service boundaries;
tracing must never change behavior when disabled.

Required trace metadata: request, run, thread, organization, principal, agent
version, profile, action ID/digest, approval ID, and safe provider reference.
Prompts, tool inputs, and outputs containing regulated or tenant data should be
sampled/redacted according to deployment policy. Never log credentials,
authorization headers, entity secrets, or raw signing material.

## MCP 2.0 gateway

`mcp_servers.json` is the only discovery configuration. A server must be
explicitly enabled and each remote tool explicitly allowlisted. Remote names
become `mcp_<server>_<tool>` to prevent collisions. Adapters are genuine
`StructuredTool` objects, so LangGraph and LangSmith see standard tool calls.

The bundled MCP server contains advisory address and risk signals only. It
cannot pay, approve, access arbitrary tenant records, or receive Circle secrets.
Every adapter checks the authenticated principal scope. Timeouts are bounded,
errors fail closed, and no function is globally monkey-patched.

For a remote HTTP MCP deployment, add OAuth token verification, audience
restriction, TLS, egress allowlists, DNS-rebinding protection, per-server
credentials, schema pinning, response-size limits, and circuit-breaker metrics.
MCP elicitation must map into the standard approval service; it may not create
a separate approval truth.
