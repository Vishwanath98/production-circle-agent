# Architecture

The agent is one durable state machine. RAG, MCP, x402, and provider choice are
capabilities selected by a server-owned profile, not separate agents with
diverging control flow.

```mermaid
flowchart LR
    U["User or API client"] --> A["Authentication\nBearer token or HttpOnly session"]
    A --> Z["Authorization\norganization, role, scope, object"]
    Z --> G["Circle LangGraph\ndurable thread state"]
    G --> T["Native LangChain tools\n@tool spans"]
    T --> R["Tenant-filtered policy RAG"]
    T --> M["MCP 2.0 gateway\nallowlisted advisory tools"]
    T --> P["Action policy\nALLOW / DENY / REQUIRE_APPROVAL"]
    P -->|"read allowed"| O["Read result"]
    P -->|"denied"| D["Fail closed"]
    P -->|"financial effect"| H["Durable human approval"]
    H -->|"approved digest"| C["Atomic action claim"]
    C --> S["Simulator or Circle testnet SDK"]
    S --> W["Signed, deduplicated webhook"]
    W --> X["Normalized transaction state"]
    G --> AU["Tenant-scoped audit trail"]
    T --> AU
    P --> AU
    H --> AU
    S --> AU
```

## Financial-effect lifecycle

```mermaid
stateDiagram-v2
    [*] --> Proposed
    Proposed --> Denied: policy deny
    Proposed --> PendingApproval: financial effect
    PendingApproval --> Cancelled: reject or expiry
    PendingApproval --> Approved: authorized decision on exact digest
    Approved --> Executing: atomic compare-and-set claim
    Executing --> Failed: provider error
    Executing --> Submitted: provider accepted
    Submitted --> Confirmed: signed webhook or status poll
    Submitted --> Failed: signed webhook or status poll
    Confirmed --> [*]
    Denied --> [*]
    Cancelled --> [*]
    Failed --> [*]
```

Human approval is a reusable policy outcome. It is not a UI feature and is not
owned by x402, MCP, or RAG. Any sensitive action can produce the same approval
envelope. Resumption re-checks the stored tenant, action version, digest,
reviewer authorization, expiry, and status before the provider is called.

## Trust boundaries

1. The client controls text, IDs, profile requests, and idempotency keys; all
   are untrusted.
2. The authenticated runtime context is created server-side and hidden from
   model-visible tool schemas.
3. The model may propose a tool call but cannot approve or execute an action.
4. MCP output and retrieved text are untrusted data, never instructions.
5. Provider responses and webhooks are normalized and reconciled; submission
   is not finality.
6. The entity secret and API keys exist only in the provider process
   environment and are never placed in graph state, prompts, audit details, or
   browser payloads.
