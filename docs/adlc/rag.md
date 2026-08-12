# Tenant-safe policy RAG

Ingestion stores source, version, visibility, tenant, sensitivity, content
hash, actor, and deterministic chunks. The local lab uses deterministic hashing
embeddings so tests need no network. A production embedding backend can replace
the embedder without changing the authorization boundary.

Retrieval order is security-critical:

1. Resolve the authenticated principal from server context.
2. SQL-filter active chunks to `organization_id IS NULL OR organization_id = ?`.
3. Score only that authorized candidate set.
4. Apply the relevance threshold and top-k.
5. Return source, heading, version, visibility, tenant, excerpt, and score.
6. If nothing passes, return an explicit ungrounded result.

Do not use model-generated metadata filters. Do not fetch all vectors and remove
foreign results afterward. Production vector stores must enforce the same
prefilter in the query itself and should use separate namespaces/collections as
defense in depth.

Policy content informs decisions but does not directly authorize an effect.
Deterministic policy code owns the decision. Every citation used as action
evidence should be version-pinned into the action envelope before approval.
