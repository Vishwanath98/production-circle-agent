# Security, authentication, and tenancy

## Local authentication model

`setup_local.py` creates opaque `dev_<id>.<secret>` credentials. Only an scrypt
hash and salt are stored. Tokens can expire or be revoked. The browser exchanges
a development credential for an eight-hour opaque session; the session cookie
is HttpOnly and SameSite=Strict, and mutations require a separate CSRF token.

Production should replace the development credential resolver with OIDC/OAuth
access-token verification while preserving `Principal` and its downstream
contracts. Store only provider subject IDs, organization membership, roles,
scopes, status, and audit metadata. Do not store user passwords. If refresh
tokens are required, encrypt them with a managed KMS-backed key and isolate them
from the agent database.

## RBAC and ABAC

- Requester: `agent:chat`, reads, policy retrieval, and transfer request.
- Reviewer: `circle:approval:decide` plus reviewer/admin role.
- Policy editor: `policy:write` for tenant document ingestion.
- Server-owned attributes: organization, thread owner, wallet owner/custody,
  action risk, environment, and resource tenant.

Authorization is checked at the API boundary and again inside every tool or
service boundary. The model cannot supply or modify these values.

## Tenant invariants

1. Every tenant-owned durable record carries `organization_id`.
2. Reusable human-facing IDs may collide across organizations; database keys
   and lookups include the organization.
3. Threads are visible only to their owner. Reviewers see tenant approval
   summaries, not unrestricted conversations.
4. Wallets, actions, approvals, transactions, audit events, documents, chunks,
   and memories are queried with the authenticated organization.
5. Webhook organization is derived from a server-side subscription mapping,
   never a URL parameter or webhook field chosen by an agent.
6. RAG retrieves global policy plus the authenticated tenant only.
7. Long-term memory is explicit, principal-owned, sensitivity-labelled,
   expirable, and soft-deletable. It is not inferred from chat or shared across
   principals.

## Threat matrix

| Threat | Required control | Test evidence |
|---|---|---|
| IDOR/BOLA | tenant + object checks on every lookup | same wallet/thread IDs in two orgs |
| Prompt injection | tools own authorization; retrieved/MCP text treated as data | missing-scope tool denial |
| Cross-tenant RAG leak | SQL visibility prefilter before scoring | private ORCHID document absent for other org |
| Approval tampering | exact action digest/version/tenant and expiry | altered digest rejected |
| Double payment | unique tenant idempotency + atomic action claim + provider key | second claim fails |
| Provider outage | fail closed; no simulator fallback | legacy characterization plus provider-error tests |
| Forged/replayed webhook | ECDSA verification + subscription mapping + unique notification ID/hash | signature and duplicate tests |
| Secret leakage | central redaction; no secrets in state/prompts/audit | audit redaction tests |
| Mainnet accident | no mainnet profile; host and x402 network allowlists | profile/config tests |

## Production hardening before internet exposure

- Put TLS and a standards-compliant OIDC resource server in front of the API.
- Store application data in PostgreSQL with row-level security as defense in
  depth and per-tenant encryption-key strategy where required.
- Put Circle secrets in a secret manager; rotate entity secrets and API keys.
- Use restricted Circle API keys with IP allowlisting.
- Add rate limits by principal, organization, route, and action risk.
- Export append-only audit events to tamper-evident storage/SIEM.
- Add data retention, deletion, legal-hold, and backup/restore procedures.
