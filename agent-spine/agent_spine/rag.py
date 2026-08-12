"""Policy RAG for the airline agent — rebuilt.

Replaces the previous disabled in-memory numpy dot-product retriever. Design
goals (driven by the testing platform):

* Real chunking with heading context + overlap (not one chunk per ## section).
* Pluggable embedder (like the LLM provider): a deterministic, dependency-free
  HashingEmbedder for Form A (Claude/CI-runnable, no network), and an
  OpenAI-compatible embedder for the live/local-server path (Form B).
* Persisted vector store so the corpus isn't re-embedded on every boot.
* Score-thresholded top-k with an explicit "no grounded policy" path so the
  agent can say "I don't know" instead of hallucinating.
* Citations in the tool output + structured trace events (rag_query,
  rag_retrieved, rag_context) for the harness to assert grounding/faithfulness.

Framework-free (no langchain/langgraph imports) so retrieval logic is unit
runnable on a bare interpreter.
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
import os
import re
from dataclasses import asdict, dataclass
from typing import List, Optional, Protocol, Sequence

logger = logging.getLogger("airline_agent.rag")

_TOKEN_RE = re.compile(r"[a-z]{3,}")
_STOPWORDS = {
    "the", "and", "for", "are", "but", "not", "you", "your", "can", "with",
    "this", "that", "have", "has", "was", "will", "from", "any", "all", "out",
    "how", "what", "when", "where", "which", "who", "why", "into", "via",
    "may", "able", "via", "per", "about", "after", "before", "than", "then",
}


# --- trace --------------------------------------------------------------------
def _trace(event_type: str, **attributes) -> dict:
    event = {"event_type": event_type, **attributes}
    logger.info(json.dumps(event, default=str, separators=(",", ":")))
    return event


# --- chunking -----------------------------------------------------------------
@dataclass
class Chunk:
    id: str
    text: str
    heading: str
    source: str
    ordinal: int


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:40] or "section"


def chunk_markdown(
    text: str, source: str, max_chars: int = 1200, overlap: int = 150
) -> List[Chunk]:
    """Split markdown into heading-scoped, size-bounded, overlapping chunks."""
    # 1) Partition into (heading, body) sections on level-1/2 headings.
    sections: List[tuple] = []
    heading = "Introduction"
    buf: List[str] = []
    for line in text.splitlines():
        if re.match(r"^#{1,2} ", line):
            if buf:
                sections.append((heading, "\n".join(buf).strip()))
                buf = []
            heading = line.lstrip("#").strip()
        else:
            buf.append(line)
    if buf:
        sections.append((heading, "\n".join(buf).strip()))

    # 2) Window each section's body on line boundaries with overlap.
    chunks: List[Chunk] = []
    for heading, body in sections:
        if not body:
            continue
        windows = _window(body, max_chars, overlap)
        for i, window in enumerate(windows):
            cid = f"{source}#{_slug(heading)}-{i}"
            # Prepend the heading so the chunk carries its own context.
            chunk_text = f"{heading}\n{window}"
            chunks.append(Chunk(id=cid, text=chunk_text, heading=heading, source=source, ordinal=i))
    return chunks


def _window(body: str, max_chars: int, overlap: int) -> List[str]:
    if len(body) <= max_chars:
        return [body]
    lines = body.split("\n")
    windows: List[str] = []
    cur: List[str] = []
    cur_len = 0
    for line in lines:
        if cur_len + len(line) + 1 > max_chars and cur:
            windows.append("\n".join(cur))
            # carry an overlap tail of the previous window
            tail, tail_len = [], 0
            for prev in reversed(cur):
                if tail_len + len(prev) > overlap:
                    break
                tail.insert(0, prev)
                tail_len += len(prev) + 1
            cur, cur_len = list(tail), tail_len
        cur.append(line)
        cur_len += len(line) + 1
    if cur:
        windows.append("\n".join(cur))
    return windows


# --- embedders ----------------------------------------------------------------
class Embedder(Protocol):
    def embed_documents(self, texts: Sequence[str]) -> List[List[float]]: ...
    def embed_query(self, text: str) -> List[float]: ...


def _tokens(text: str) -> List[str]:
    return [t for t in _TOKEN_RE.findall(text.lower()) if t not in _STOPWORDS]


def _l2_normalize(vec: List[float]) -> List[float]:
    norm = math.sqrt(sum(v * v for v in vec))
    if norm == 0:
        return vec
    return [v / norm for v in vec]


class HashingEmbedder:
    """Deterministic, dependency-free bag-of-words embedder (feature hashing).

    Good enough to exercise retrieval/grounding logic offline. Swap for a real
    embedding model (OpenAICompatibleEmbedder / Voyage) in production.
    """

    name = "hashing"

    def __init__(self, dim: int = 16384):
        self.dim = dim

    def _embed_one(self, text: str) -> List[float]:
        vec = [0.0] * self.dim
        for tok in _tokens(text):
            h = int(hashlib.md5(tok.encode()).hexdigest(), 16) % self.dim
            vec[h] += 1.0
        return _l2_normalize(vec)

    def embed_documents(self, texts: Sequence[str]) -> List[List[float]]:
        return [self._embed_one(t) for t in texts]

    def embed_query(self, text: str) -> List[float]:
        return self._embed_one(text)


class OpenAICompatibleEmbedder:
    """Live embedder hitting an OpenAI-compatible /v1/embeddings endpoint.

    Used for the local self-hosted embedding server (e.g. nomic) or any
    OpenAI-compatible provider. Stdlib-only (urllib) so it needs no extra deps.
    """

    name = "openai-compatible"

    def __init__(self, base_url: str, model: str, api_key: str = "", query_prefix: str = "", doc_prefix: str = ""):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key = api_key
        self.query_prefix = query_prefix
        self.doc_prefix = doc_prefix

    def _post(self, inputs: List[str]) -> List[List[float]]:
        import urllib.request

        payload = json.dumps({"model": self.model, "input": inputs}).encode()
        req = urllib.request.Request(
            f"{self.base_url}/embeddings",
            data=payload,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key or 'placeholder'}",
            },
        )
        with urllib.request.urlopen(req) as resp:
            data = json.loads(resp.read().decode())
        return [_l2_normalize(item["embedding"]) for item in data["data"]]

    def embed_documents(self, texts: Sequence[str]) -> List[List[float]]:
        return self._post([f"{self.doc_prefix}{t}" for t in texts])

    def embed_query(self, text: str) -> List[float]:
        return self._post([f"{self.query_prefix}{text}"])[0]


# --- vector store -------------------------------------------------------------
def _dot(a: List[float], b: List[float]) -> float:
    return sum(x * y for x, y in zip(a, b))


@dataclass
class RetrievedChunk:
    text: str
    heading: str
    source: str
    score: float


class VectorStore:
    def __init__(self):
        self.chunks: List[Chunk] = []
        self.vectors: List[List[float]] = []

    def add(self, chunks: Sequence[Chunk], vectors: Sequence[List[float]]) -> None:
        self.chunks.extend(chunks)
        self.vectors.extend(vectors)

    def search(self, query_vec: List[float], k: int, min_score: float) -> List[RetrievedChunk]:
        scored = [
            (chunk, _dot(query_vec, vec))
            for chunk, vec in zip(self.chunks, self.vectors)
        ]
        scored.sort(key=lambda cs: cs[1], reverse=True)
        hits = []
        for chunk, score in scored[:k]:
            if score < min_score:
                continue
            hits.append(
                RetrievedChunk(text=chunk.text, heading=chunk.heading, source=chunk.source, score=round(score, 4))
            )
        return hits

    def save(self, path: str) -> None:
        with open(path, "w") as f:
            json.dump(
                {"chunks": [asdict(c) for c in self.chunks], "vectors": self.vectors},
                f,
            )

    @classmethod
    def load(cls, path: str) -> "VectorStore":
        store = cls()
        with open(path) as f:
            data = json.load(f)
        store.chunks = [Chunk(**c) for c in data["chunks"]]
        store.vectors = data["vectors"]
        return store


# --- retriever ----------------------------------------------------------------
@dataclass
class RetrievalResult:
    query: str
    hits: List[RetrievedChunk]
    grounded: bool
    context: str


class PolicyRetriever:
    def __init__(self, store: VectorStore, embedder: Embedder, min_score: float = 0.1):
        self.store = store
        self.embedder = embedder
        self.min_score = min_score

    @classmethod
    def from_corpus(
        cls,
        corpus_path: str,
        embedder: Embedder,
        cache_path: Optional[str] = None,
        min_score: float = 0.1,
    ) -> "PolicyRetriever":
        if cache_path and os.path.exists(cache_path):
            store = VectorStore.load(cache_path)
            return cls(store, embedder, min_score)

        with open(corpus_path) as f:
            text = f.read()
        chunks = chunk_markdown(text, source=os.path.basename(corpus_path))
        vectors = embedder.embed_documents([c.text for c in chunks])
        store = VectorStore()
        store.add(chunks, vectors)
        if cache_path:
            store.save(cache_path)
        return cls(store, embedder, min_score)

    def query(self, text: str, k: int = 4) -> RetrievalResult:
        _trace("rag_query", query=text, k=k, min_score=self.min_score, embedder=getattr(self.embedder, "name", "?"))
        query_vec = self.embedder.embed_query(text)
        hits = self.store.search(query_vec, k=k, min_score=self.min_score)
        _trace(
            "rag_retrieved",
            query=text,
            hits=[{"heading": h.heading, "source": h.source, "score": h.score} for h in hits],
        )
        grounded = len(hits) > 0
        context = self._format_context(hits)
        _trace("rag_context", query=text, grounded=grounded, context_chars=len(context))
        return RetrievalResult(query=text, hits=hits, grounded=grounded, context=context)

    @staticmethod
    def _format_context(hits: List[RetrievedChunk]) -> str:
        if not hits:
            return (
                "No relevant policy was found in the Swiss Air policy documents. "
                "Tell the user you don't have a documented policy for this and do "
                "not invent one."
            )
        blocks = []
        for i, h in enumerate(hits, 1):
            blocks.append(f"[{i}] (source: {h.source} § {h.heading}, score={h.score})\n{h.text}")
        return (
            "Answer using ONLY the policy excerpts below and cite the bracketed "
            "source numbers you rely on. If they don't cover the question, say so.\n\n"
            + "\n\n".join(blocks)
        )
