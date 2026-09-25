"""Run queued PDF ingestion inside the API service, one document at a time."""

from __future__ import annotations

import logging
import os

import psycopg
from psycopg.rows import dict_row

INGESTION_LOCK_KEY = (193612, 1)
MAX_INTERRUPTED_ATTEMPTS = 2
logger = logging.getLogger(__name__)


def drain_pending_documents(wait_for_lock: bool = True) -> None:
    """Process durable upload requests; a restart can resume interrupted work."""
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        return

    try:
        with psycopg.connect(database_url, row_factory=dict_row) as connection:
            # Session lock also serializes the local maintenance CLI with API uploads.
            if wait_for_lock:
                connection.execute("SELECT pg_advisory_lock(%s, %s)", INGESTION_LOCK_KEY)
            elif not connection.execute(
                "SELECT pg_try_advisory_lock(%s, %s) AS acquired", INGESTION_LOCK_KEY
            ).fetchone()["acquired"]:
                return
            connection.commit()
            try:
                connection.execute(
                    """UPDATE documents SET ingestion_queued_at = NULL
                       WHERE ingestion_queued_at IS NOT NULL
                         AND review_status IN ('ready', 'ready_with_warnings',
                                               'approved', 'rejected', 'failed')"""
                )
                connection.commit()
                while True:
                    document = connection.execute(
                        """SELECT d.document_id, d.pdf_bytes, d.plan_id, d.uploaded_by_firebase_uid,
                                  d.ingestion_attempts, p.plan_name, p.insurer
                           FROM documents d LEFT JOIN plans p USING (plan_id)
                           WHERE d.ingestion_queued_at IS NOT NULL
                             AND d.review_status IN ('uploaded', 'processing', 'needs_review')
                           ORDER BY d.ingestion_queued_at, d.document_id LIMIT 1"""
                    ).fetchone()
                    if document is None:
                        break
                    document_id = document["document_id"]
                    if document["ingestion_attempts"] >= MAX_INTERRUPTED_ATTEMPTS:
                        connection.execute(
                            """UPDATE documents SET review_status = 'failed',
                               ingestion_error = 'Automatic ingestion was interrupted twice. Use Retry to try again.',
                               ingestion_queued_at = NULL WHERE document_id = %s""",
                            (document_id,),
                        )
                        connection.commit()
                        continue

                    connection.execute(
                        "UPDATE documents SET ingestion_attempts = ingestion_attempts + 1 WHERE document_id = %s",
                        (document_id,),
                    )
                    connection.commit()
                    try:
                        from app.pipeline import process_document

                        result = process_document(connection, dict(document))
                        if result["status"] not in {"approved", "ready", "ready_with_warnings", "failed"}:
                            raise RuntimeError(f"Unexpected ingestion status: {result['status']}")
                    except Exception as exc:
                        connection.rollback()
                        logger.exception("Automatic ingestion failed for document %s", document_id)
                        connection.execute(
                            """UPDATE documents SET review_status = 'failed',
                               ingestion_error = %s, ingestion_queued_at = NULL
                               WHERE document_id = %s""",
                            (f"Automatic ingestion failed: {type(exc).__name__}: {exc}"[:2000], document_id),
                        )
                    else:
                        connection.execute(
                            "UPDATE documents SET ingestion_queued_at = NULL WHERE document_id = %s",
                            (document_id,),
                        )
                    connection.commit()
            finally:
                connection.rollback()
                connection.execute("SELECT pg_advisory_unlock(%s, %s)", INGESTION_LOCK_KEY)
                connection.commit()
    except Exception:
        logger.exception("Could not drain automatic ingestion queue")
