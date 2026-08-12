# Onboarding migration to the shared foundation

Status: implemented in the local lab; production promotion remains gated.

Onboarding should reuse the foundation after Circle acceptance; it should not
copy Circle payment code. The reusable parts are principal/context, durable
threads, credentials/sessions, tool catalog, MCP gateway, audit, tenant-safe
RAG, API error/auth conventions, and the three-outcome policy/approval model.

Implemented work packages:

1. Preserve current base/RAG/MCP modules as the legacy comparison surface.
2. Define onboarding identities, tenant-owned applications, documents, field
   sensitivity, roles, scopes, and state transitions.
3. Build one durable graph with `core-sim`, `rag-sim`, `mcp-sim`, and `full-sim` profiles.
4. Convert model affordances to native `@tool`; keep approval/finalization
   service-only.
5. Move policy documents into tenant-safe RAG with citations and versions.
6. Route KYB review, elevated-risk decisions, and external submissions through
   the standard action envelope and approval service.
7. Use MCP only for allowlisted advisory checks; never expose application
   approval as a remote/model tool.
8. Serve it through an authenticated native `/chat`, approval, and application API.
9. Add cross-tenant applications/documents, prompt injection, reviewer,
   idempotency, restart, and provider failure tests.

Onboarding domain policy remains separate from Circle transfer policy. Both use
the same action and approval infrastructure without intermixing financial and
KYB rules. A fuller Onboarding operations console can reuse the Circle console
session and component conventions after the domain workflow is accepted.
