"""Local BM25 and FAISS retrieval over approved, provenance-bearing chunks."""

from __future__ import annotations

import os
import re
import time
import hashlib
from functools import lru_cache
from typing import Any

MODEL_NAME = os.getenv("EMBEDDING_MODEL", "sentence-transformers/all-MiniLM-L6-v2")
MODEL_VERSION = os.getenv("EMBEDDING_MODEL_VERSION", "all-MiniLM-L6-v2")


def tokenize(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", text.lower())


@lru_cache(maxsize=1)
def _model():
    from sentence_transformers import SentenceTransformer

    return SentenceTransformer(MODEL_NAME)


@lru_cache(maxsize=1)
def model_fingerprint() -> str:
    """Hash loaded model weights so a version label cannot silently mask a model change."""
    model = _model()
    digest = hashlib.sha256()
    digest.update(f"{MODEL_NAME}\0{MODEL_VERSION}\0{model.get_sentence_embedding_dimension()}".encode())
    for key, tensor in sorted(model.state_dict().items()):
        value = tensor.detach().cpu().contiguous()
        digest.update(key.encode())
        digest.update(str(tuple(value.shape)).encode())
        digest.update(str(value.dtype).encode())
        digest.update(value.numpy().tobytes())
    return digest.hexdigest()


def encode_texts(texts: list[str]):
    import numpy as np

    vectors = _model().encode(texts, normalize_embeddings=True, convert_to_numpy=True)
    return np.asarray(vectors, dtype="float32")


def approved_chunks(connection, strategy: str, strategy_version: int = 1, plan_id: int | None = None,
                    document_id: int | None = None, section: str | None = None) -> list[dict[str, Any]]:
    filters = ["d.review_status = 'approved'", "d.corpus_status <> 'ineligible'",
               "c.chunk_strategy = %s", "c.strategy_version = %s"]
    params: list[Any] = [strategy, strategy_version]
    if plan_id is not None:
        filters.append("d.plan_id = %s")
        params.append(plan_id)
    if document_id is not None:
        filters.append("d.document_id = %s")
        params.append(document_id)
    if section:
        filters.append("c.provenance::text ILIKE %s")
        params.append(f"%{section}%")
    rows = connection.execute(
        f"""SELECT c.chunk_id, c.document_id, d.plan_id, p.plan_name,
                   d.original_filename, c.chunk_text, c.page_start, c.page_end,
                   c.provenance
            FROM chunks c JOIN documents d USING (document_id)
            LEFT JOIN plans p USING (plan_id)
            WHERE {' AND '.join(filters)} ORDER BY c.chunk_id""", tuple(params)
    ).fetchall()
    return [dict(row) for row in rows]


def retrieve(connection, question: str, method: str, strategy: str, top_k: int = 5,
             strategy_version: int = 1, plan_id: int | None = None, document_id: int | None = None,
             section: str | None = None) -> dict[str, Any]:
    start = time.perf_counter()
    chunks = approved_chunks(connection, strategy, strategy_version, plan_id, document_id, section)
    corpus_load_ms = (time.perf_counter() - start) * 1000
    if not chunks:
        total = (time.perf_counter() - start) * 1000
        return {"results": [], "latency_ms": total, "timings": {
            "corpus_load_ms": corpus_load_ms, "embedding_load_ms": 0.0, "index_build_ms": 0.0,
            "query_embedding_ms": 0.0, "model_load_ms": 0.0,
            "search_ms": 0.0, "total_request_ms": total}}
    index_started = time.perf_counter()
    if method == "bm25":
        from rank_bm25 import BM25Okapi

        model = BM25Okapi([tokenize(chunk["chunk_text"]) for chunk in chunks])
        index_build_ms = (time.perf_counter() - index_started) * 1000
        search_started = time.perf_counter()
        scores = model.get_scores(tokenize(question))
        order = sorted(range(len(chunks)), key=lambda i: float(scores[i]), reverse=True)
        ranked = [(i, float(scores[i])) for i in order if float(scores[i]) > 0][:top_k]
        search_ms = (time.perf_counter() - search_started) * 1000
        query_embedding_ms = model_load_ms = 0.0
    elif method == "semantic":
        import faiss
        import numpy as np

        was_loaded = _model.cache_info().currsize > 0
        model_started = time.perf_counter()
        fingerprint = model_fingerprint()
        sentence_model = _model()
        expected_dimension = sentence_model.get_sentence_embedding_dimension()
        model_load_ms = (time.perf_counter() - model_started) * 1000 if not was_loaded else 0.0
        embedding_filters = ["d.review_status = 'approved'", "d.corpus_status <> 'ineligible'", "c.chunk_strategy = %s",
                             "c.strategy_version = %s", "ce.model_name = %s", "ce.model_version = %s",
                             "ce.model_fingerprint = %s"]
        embedding_params: list[Any] = [strategy, strategy_version, MODEL_NAME, MODEL_VERSION, fingerprint]
        if plan_id is not None:
            embedding_filters.append("d.plan_id = %s")
            embedding_params.append(plan_id)
        if document_id is not None:
            embedding_filters.append("d.document_id = %s")
            embedding_params.append(document_id)
        if section:
            embedding_filters.append("c.provenance::text ILIKE %s")
            embedding_params.append(f"%{section}%")

        embedding_started = time.perf_counter()
        embedding = connection.execute(
            f"""SELECT ce.chunk_id, ce.embedding_values, ce.model_fingerprint
               FROM chunk_embeddings ce JOIN chunks c USING (chunk_id)
               JOIN documents d USING (document_id)
               WHERE {' AND '.join(embedding_filters)}
               ORDER BY ce.chunk_id""", tuple(embedding_params)
        ).fetchall()
        embedding_load_ms = (time.perf_counter() - embedding_started) * 1000
        by_id = {row["chunk_id"]: index for index, row in enumerate(chunks)}
        kept = [dict(row) for row in embedding if row["chunk_id"] in by_id]
        if not kept:
            return {"results": [], "latency_ms": (time.perf_counter() - start) * 1000,
                    "index_status": "no_approved_embeddings", "timings": {
                        "corpus_load_ms": corpus_load_ms, "embedding_load_ms": embedding_load_ms,
                        "index_build_ms": 0.0, "query_embedding_ms": 0.0,
                        "model_load_ms": model_load_ms,
                        "search_ms": 0.0, "total_request_ms": (time.perf_counter() - start) * 1000}}
        try:
            matrix = np.asarray([row["embedding_values"] for row in kept], dtype="float32")
        except (TypeError, ValueError, OverflowError) as exc:
            raise EmbeddingDataError("Stored embeddings contain non-numeric values; regenerate embeddings.") from exc
        if matrix.ndim != 2 or matrix.shape[1] != expected_dimension:
            raise EmbeddingDataError("Stored embedding dimensions do not match the configured model; regenerate embeddings.")
        if not np.isfinite(matrix).all():
            raise EmbeddingDataError("Stored embeddings contain non-finite values; regenerate embeddings.")
        norms = np.linalg.norm(matrix, axis=1)
        if not np.isfinite(norms).all() or np.any(norms <= 0):
            raise EmbeddingDataError("Stored embeddings contain zero vectors; regenerate embeddings.")
        index_started = time.perf_counter()
        faiss.normalize_L2(matrix)
        index = faiss.IndexFlatIP(matrix.shape[1])
        index.add(matrix)
        index_build_ms = (time.perf_counter() - index_started) * 1000
        query_started = time.perf_counter()
        query = np.asarray(sentence_model.encode([question], normalize_embeddings=True,
                                                  convert_to_numpy=True), dtype="float32")
        query_embedding_ms = (time.perf_counter() - query_started) * 1000
        search_started = time.perf_counter()
        distances, positions = index.search(query, min(top_k, len(kept)))
        ranked = [(by_id[kept[int(pos)]["chunk_id"]], float(score))
                  for score, pos in zip(distances[0], positions[0]) if pos >= 0]
        search_ms = (time.perf_counter() - search_started) * 1000
    else:
        raise ValueError("method must be bm25 or semantic")
    results = []
    for rank, (index, score) in enumerate(ranked, 1):
        chunk = chunks[index]
        results.append({**chunk, "rank": rank, "score": score})
    total = (time.perf_counter() - start) * 1000
    return {"results": results, "latency_ms": total, "timings": {
        "corpus_load_ms": corpus_load_ms,
        "embedding_load_ms": 0.0 if method == "bm25" else embedding_load_ms,
        "index_build_ms": index_build_ms,
        "query_embedding_ms": query_embedding_ms, "model_load_ms": model_load_ms,
        "search_ms": search_ms, "total_request_ms": total}}


class EmbeddingDataError(RuntimeError):
    """Stored semantic vectors are malformed or incompatible with the configured model."""


def make_document_embeddings(connection, batch_size: int = 32) -> dict[str, int]:
    """Create local embeddings for chunks of reviewed, approved documents."""
    fingerprint = model_fingerprint()
    rows = connection.execute(
        """SELECT c.chunk_id, c.chunk_text FROM chunks c
           JOIN documents d USING (document_id)
           LEFT JOIN chunk_embeddings e ON e.chunk_id = c.chunk_id
             AND e.model_name = %s AND e.model_version = %s
           WHERE d.review_status = 'approved' AND d.corpus_status <> 'ineligible'
             AND (e.embedding_id IS NULL OR e.model_fingerprint IS DISTINCT FROM %s)
           ORDER BY c.chunk_id""", (MODEL_NAME, MODEL_VERSION, fingerprint)
    ).fetchall()
    inserted = 0
    for offset in range(0, len(rows), batch_size):
        batch = rows[offset:offset + batch_size]
        vectors = encode_texts([row["chunk_text"] for row in batch])
        with connection.transaction():
            for row, vector in zip(batch, vectors):
                connection.execute(
                    """INSERT INTO chunk_embeddings
                       (chunk_id, model_name, model_version, model_fingerprint, embedding_values)
                       VALUES (%s,%s,%s,%s,%s)
                       ON CONFLICT (chunk_id, model_name, model_version) DO UPDATE SET
                         model_fingerprint = EXCLUDED.model_fingerprint,
                         embedding_values = EXCLUDED.embedding_values,
                         created_at = now()""",
                    (row["chunk_id"], MODEL_NAME, MODEL_VERSION, fingerprint, vector.tolist()),
                )
                inserted += 1
    return {"embedded": inserted, "model_name": MODEL_NAME,
            "model_version": MODEL_VERSION, "model_fingerprint": fingerprint}
