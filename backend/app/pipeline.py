"""One local command to parse, extract, embed, and assess uploaded PDFs."""

from __future__ import annotations

import argparse
import os
from pathlib import Path

import psycopg
import numpy as np
from dotenv import load_dotenv
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from app.benefits import extract_candidates
from app.ingest import ingest_document
from app.retrieval import MODEL_NAME, MODEL_VERSION, make_document_embeddings, model_dimension, model_fingerprint

load_dotenv(Path(__file__).resolve().parents[2] / ".env")


def _save(connection, document_id: int, stages: dict, warnings: list[str],
          status: str, error: str | None = None) -> None:
    connection.execute(
        """UPDATE documents SET processing_stages = %s, processing_warnings = %s,
           review_status = %s, ingestion_error = %s WHERE document_id = %s""",
        (Jsonb(stages), Jsonb(warnings), status, error, document_id),
    )
    connection.commit()


def readiness_status(stages: dict[str, str], warnings: list[str], counts: dict) -> str:
    """Promote only complete, retrievable evidence; keep partial issues visible."""
    if any(stages.get(stage) == "failed" for stage in stages):
        return "failed"
    if any(stages.get(stage) != "completed" for stage in
           ("parsing", "chunking", "benefit_extraction", "embedding")):
        return "needs_review"
    if any(strategy not in counts or counts[strategy]["total"] == 0
           or counts[strategy]["embedded"] != counts[strategy]["total"]
           for strategy in ("fixed_size", "section_aware")):
        return "failed"
    return "ready_with_warnings" if warnings else "ready"


def process_document(connection, document: dict) -> dict:
    document_id = document["document_id"]
    stages = {name: "pending" for name in ("parsing", "chunking", "benefit_extraction", "embedding")}
    warnings: list[str] = []
    if not document.get("plan_id") or not str(document.get("plan_name") or "").strip() or not str(document.get("insurer") or "").strip():
        stages["parsing"] = "failed"
        _save(connection, document_id, stages, warnings, "failed", "Document plan identity is missing.")
        return {"document_id": document_id, "status": "failed", "error": "Document plan identity is missing."}
    parsed = ingest_document(connection, document)
    if parsed.get("error"):
        return {**parsed, "status": "failed"}
    warnings.extend(parsed["issues"])
    stages.update({"parsing": "completed", "chunking": "completed", "benefit_extraction": "running"})
    _save(connection, document_id, stages, warnings, "needs_review")
    try:
        pages = connection.execute(
            """SELECT page_id, page_number, section_heading, extracted_text AS text, tables_json
               FROM document_pages WHERE document_id = %s AND parse_status <> 'failed'
               ORDER BY page_number""", (document_id,)
        ).fetchall()
        candidates = extract_candidates([{**dict(page), "tables": page["tables_json"] or []} for page in pages])
        page_ids = {page["page_number"]: page["page_id"] for page in pages}
        with connection.transaction():
            for candidate in candidates:
                connection.execute(
                    """INSERT INTO benefit_records
                       (plan_id, document_id, category, value_text, dimensions, source_page_id,
                        source_section, verification_status)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
                       ON CONFLICT (document_id, source_page_id, category, value_text) DO NOTHING""",
                    (document["plan_id"], document_id, candidate.category, candidate.value_text,
                     Jsonb(candidate.dimensions), page_ids[candidate.page_number], candidate.section,
                     candidate.status),
                )
        ambiguous = sum(candidate.status == "ambiguous" for candidate in candidates)
        if ambiguous:
            warnings.append(f"{ambiguous} ambiguous benefit candidate(s) require context or optional correction.")
        untraceable = sum(not candidate.section for candidate in candidates)
        if untraceable:
            warnings.append(f"{untraceable} benefit candidate(s) lack a detected section and cannot support cited answers.")
        stages["benefit_extraction"] = "completed"
        stages["embedding"] = "running"
        _save(connection, document_id, stages, warnings, "needs_review")
    except Exception as exc:
        error = f"Benefit extraction failed: {type(exc).__name__}: {exc}"[:2000]
        stages["benefit_extraction"] = "failed"
        _save(connection, document_id, stages, warnings, "failed", error)
        return {"document_id": document_id, "status": "failed", "error": error}
    try:
        make_document_embeddings(connection, document_id=document_id)
        fingerprint = model_fingerprint()
        counts = connection.execute(
            """SELECT c.chunk_strategy, count(*) AS total,
                      count(e.embedding_id) AS embedded,
                      array_agg(e.embedding_values) AS vectors
               FROM chunks c LEFT JOIN chunk_embeddings e ON e.chunk_id = c.chunk_id
                 AND e.model_name = %s AND e.model_version = %s AND e.model_fingerprint = %s
               WHERE c.document_id = %s GROUP BY c.chunk_strategy""",
            (MODEL_NAME, MODEL_VERSION, fingerprint, document_id),
        ).fetchall()
        by_strategy = {row["chunk_strategy"]: row for row in counts}
        stages["embedding"] = "completed"
        if readiness_status(stages, warnings, by_strategy) == "failed":
            raise ValueError("Embeddings are insufficient for both retrieval strategies.")
        dimension = model_dimension()
        for row in counts:
            vectors = np.asarray(row["vectors"], dtype="float32")
            if vectors.ndim != 2 or vectors.shape[1] != dimension or not np.isfinite(vectors).all() or np.any(np.linalg.norm(vectors, axis=1) == 0):
                raise ValueError("Stored embeddings contain invalid vectors.")
        status = readiness_status(stages, warnings, by_strategy)
        _save(connection, document_id, stages, warnings, status)
        return {"document_id": document_id, "status": status, "stages": stages,
                "warnings": warnings, "candidates": len(candidates)}
    except Exception as exc:
        error = f"Embedding failed: {type(exc).__name__}: {exc}"[:2000]
        stages["embedding"] = "failed"
        _save(connection, document_id, stages, warnings, "failed", error)
        return {"document_id": document_id, "status": "failed", "error": error, "stages": stages}


def main() -> None:
    parser = argparse.ArgumentParser(description="Process uploaded PDFs into queryable evidence.")
    parser.add_argument("--reprocess-id", type=int, help="Reprocess one document, replacing derived evidence.")
    args = parser.parse_args()
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        raise SystemExit("DATABASE_URL is required in the repository-root .env file.")
    with psycopg.connect(database_url, row_factory=dict_row) as connection:
        rows = connection.execute(
            """SELECT d.document_id, d.pdf_bytes, d.plan_id, p.plan_name, p.insurer
               FROM documents d LEFT JOIN plans p USING (plan_id)
               WHERE (%s::bigint IS NULL AND d.review_status = 'uploaded')
                  OR (%s::bigint = d.document_id AND d.review_status IN
                      ('uploaded', 'failed', 'needs_review', 'ready', 'ready_with_warnings', 'approved', 'rejected'))
               ORDER BY d.document_id""", (args.reprocess_id, args.reprocess_id),
        ).fetchall()
        if not rows:
            print("No eligible documents are waiting for processing.")
        failures = 0
        for row in rows:
            result = process_document(connection, dict(row))
            print(result)
            failures += result["status"] == "failed"
        if failures:
            raise SystemExit(1)


if __name__ == "__main__":
    main()
