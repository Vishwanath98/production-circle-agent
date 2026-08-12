import hashlib
import os

from agent_spine.rag import HashingEmbedder, chunk_markdown


MIN_SCORE = 0.25


def cosine(a, b):
    value = 0.0
    for left, right in zip(a, b):
        value += left * right
    return value


def document_ingest(store, organization_id, source_name, version, content,
                    actor_id, visibility='tenant', sensitivity='internal'):
    if visibility == 'global_policy':
        organization_id = None
    elif not organization_id:
        raise ValueError('tenant document requires an organization_id')
    content_hash = hashlib.sha256(content.encode('utf-8')).hexdigest()
    namespace = organization_id or 'global'
    stable = '%s:%s:%s' % (namespace, source_name, version)
    document_id = 'doc_%s' % hashlib.sha256(stable.encode('utf-8')).hexdigest()[:32]
    source_chunks = chunk_markdown(content, source=source_name)
    embedder = HashingEmbedder()
    vectors = embedder.embed_documents([item.text for item in source_chunks])
    chunks = []
    for ordinal, values in enumerate(zip(source_chunks, vectors)):
        item, vector = values
        chunk = {
            'chunk_id': '%s_%s' % (document_id, ordinal),
            'ordinal': ordinal,
            'heading': item.heading,
            'content': item.text,
            'embedding': vector,
        }
        chunks.append(chunk)
    document = {
        'document_id': document_id,
        'organization_id': organization_id,
        'visibility': visibility,
        'source_name': source_name,
        'version': version,
        'content_hash': content_hash,
        'sensitivity': sensitivity,
        'ingestion_actor_id': actor_id,
        'status': 'active',
    }
    store.document_upsert(document, chunks)
    result = dict(document)
    result['chunk_count'] = len(chunks)
    return result


def corpus_ingest(store, corpus_dir, actor_id='system'):
    results = []
    names = sorted(os.listdir(corpus_dir))
    for name in names:
        if not name.endswith('.md'):
            continue
        path = os.path.join(corpus_dir, name)
        with open(path, 'rt') as f:
            content = f.read()
        result = document_ingest(
            store, None, name, 'seed-1', content, actor_id,
            visibility='global_policy', sensitivity='public',
        )
        results.append(result)
    return results


def search(store, organization_id, query, k=4, min_score=MIN_SCORE):
    rows = store.chunk_list(organization_id)
    embedder = HashingEmbedder()
    query_vector = embedder.embed_query(query)
    scored = []
    for row in rows:
        score = cosine(query_vector, row['embedding'])
        if score < min_score:
            continue
        scored.append((score, row))
    scored.sort(key=lambda item: item[0], reverse=True)
    citations = []
    for score, row in scored[:int(k)]:
        citation = {
            'citation_id': row['chunk_id'], 'source': row['source_name'],
            'heading': row['heading'], 'excerpt': row['content'],
            'score': round(score, 4), 'visibility': row['visibility'],
            'organization_id': row['organization_id'], 'version': row['version'],
        }
        citations.append(citation)
    result = {
        'query': query, 'grounded': len(citations) > 0, 'citations': citations,
        'message': '' if citations else 'No authorized policy source grounded an answer.',
    }
    return result
