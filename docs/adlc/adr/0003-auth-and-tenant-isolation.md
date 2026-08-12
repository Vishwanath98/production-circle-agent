# ADR 0003: Server-owned identity and tenant-first storage

Status: accepted.

Decision: identity is resolved before the graph and injected through hidden
runtime config. Every tenant-owned lookup includes organization context. RAG
prefilters authorized chunks before similarity search. Webhook tenancy comes
from a server-side subscription mapping.

Consequences: organization, roles, scopes, and approval authority never appear
in model tool arguments. Development tokens are hashed; production swaps the
resolver for OIDC without changing the principal contract.
