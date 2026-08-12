from agent_spine.tenant_rag import corpus_ingest, document_ingest, search

from circle_agent.service import store_for_context


def policy_search(ctx, query, k=4):
    store = store_for_context(ctx)
    return search(store, ctx.principal.organization_id, query, k=k)
