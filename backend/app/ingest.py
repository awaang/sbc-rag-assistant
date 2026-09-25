"""Fetch uploaded PDFs from Neon and parse/chunk them on the local machine."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import re

import psycopg
from dotenv import load_dotenv
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from app.auto_ingestion import INGESTION_LOCK_KEY
from app.ingestion import _is_heading, build_chunks, parse_pdf

load_dotenv(Path(__file__).resolve().parents[2] / ".env")


def _section_heading(text: str) -> str | None:
    headings: list[str] = []
    for line in text.splitlines():
        value = " ".join(line.split())
        if _is_heading(value):
            if value not in headings:
                headings.append(value)
    return headings[0] if len(headings) == 1 else None


def ingest_document(connection: psycopg.Connection, document: dict) -> dict:
    document_id = document["document_id"]
    connection.execute("""UPDATE documents SET review_status = 'processing', ingestion_error = NULL,
                       processing_stages = %s, processing_warnings = '[]'::jsonb
                       WHERE document_id = %s""",
                       (Jsonb({"parsing": "running", "chunking": "pending",
                               "benefit_extraction": "pending", "embedding": "pending"}), document_id))
    connection.commit()
    try:
        pages = parse_pdf(bytes(document["pdf_bytes"]))
        chunks = build_chunks(pages)
        issues = []
        for page in pages:
            if page.get("parse_error"):
                issues.append(page["parse_error"])
            if page.get("table_error"):
                issues.append(page["table_error"])
            if not page["text"].strip() and not page["tables"]:
                issues.append(f"Page {page['page_number']} contains no extractable text or tables (possibly scanned).")
        usable_text = sum(len(re.findall(r"[A-Za-z0-9]", page["text"] + " ".join(
            str(cell or "") for table in page["tables"] for row in table.get("rows", []) for cell in row)))
            for page in pages)
        critical = ("Essentially no usable text was extracted." if usable_text < 50 else
                    "Both chunk strategies need usable evidence." if any(not group for group in chunks.values()) else None)
        stages = {"parsing": "completed" if not critical else "failed",
                  "chunking": "completed" if not critical else "failed",
                  "benefit_extraction": "pending", "embedding": "pending"}
        with connection.transaction():
            connection.execute("DELETE FROM benefit_records WHERE document_id = %s", (document_id,))
            connection.execute("DELETE FROM chunks WHERE document_id = %s", (document_id,))
            connection.execute("DELETE FROM document_pages WHERE document_id = %s", (document_id,))
            for page in pages:
                readable = bool(page["text"].strip() or page["tables"])
                connection.execute(
                    """INSERT INTO document_pages
                       (document_id, page_number, section_heading, extracted_text, tables_json, parse_status)
                       VALUES (%s,%s,%s,%s,%s,%s)
                       ON CONFLICT (document_id, page_number) DO UPDATE SET
                         section_heading = EXCLUDED.section_heading,
                         extracted_text = EXCLUDED.extracted_text,
                         tables_json = EXCLUDED.tables_json,
                         parse_status = EXCLUDED.parse_status""",
                    (document_id, page["page_number"], _section_heading(page["text"]), page["text"],
                     Jsonb(page["tables"]), "failed" if page.get("parse_error") else "parsed" if readable else "needs_review"),
                )
            for strategy, strategy_chunks in chunks.items():
                for chunk in strategy_chunks:
                    connection.execute(
                        """INSERT INTO chunks
                           (document_id, chunk_strategy, strategy_version, chunk_text, page_start, page_end, provenance)
                           VALUES (%s,%s,1,%s,%s,%s,%s)""",
                        (document_id, strategy, chunk["text"], chunk["page_start"], chunk["page_end"],
                         Jsonb(chunk["provenance"])),
                    )
            connection.execute(
                """UPDATE documents SET review_status = %s, ingestion_error = %s,
                   processing_stages = %s, processing_warnings = %s WHERE document_id = %s""",
                ("failed" if critical else "needs_review", critical,
                 Jsonb(stages), Jsonb(issues), document_id),
            )
        return {"document_id": document_id, "pages": len(pages),
                "fixed_size_chunks": len(chunks["fixed_size"]),
                "section_aware_chunks": len(chunks["section_aware"]), "issues": issues,
                "error": critical}
    except Exception as exc:
        message = f"{type(exc).__name__}: {exc}"[:2000]
        connection.execute(
            """UPDATE documents SET review_status = 'failed', ingestion_error = %s,
               processing_stages = %s WHERE document_id = %s""",
            (message, Jsonb({"parsing": "failed", "chunking": "pending",
                             "benefit_extraction": "pending", "embedding": "pending"}), document_id),
        )
        connection.commit()
        return {"document_id": document_id, "error": message}


def main() -> None:
    parser = argparse.ArgumentParser(description="Ingest uploaded documents from Neon.")
    parser.add_argument("--reprocess-id", type=int, help="Reparse one document for maintenance.")
    args = parser.parse_args()
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        raise SystemExit("DATABASE_URL is required in the repository-root .env file.")
    with psycopg.connect(database_url, row_factory=dict_row) as connection:
        connection.execute("SELECT pg_advisory_lock(%s, %s)", INGESTION_LOCK_KEY)
        connection.commit()
        if args.reprocess_id is None:
            pending = connection.execute(
                """SELECT document_id, pdf_bytes FROM documents WHERE review_status = 'uploaded'
                   ORDER BY document_id"""
            ).fetchall()
        else:
            pending = connection.execute(
                """SELECT document_id, pdf_bytes FROM documents
                   WHERE document_id = %s AND review_status IN
                     ('approved', 'ready', 'ready_with_warnings', 'needs_review', 'failed')""",
                (args.reprocess_id,),
            ).fetchall()
        if not pending:
            print("No eligible documents are waiting for ingestion.")
            return
        for document in pending:
            result = ingest_document(connection, document)
            print(result)


def embed_main() -> None:
    """Embed approved chunks locally and persist the vectors to Neon."""
    from app.retrieval import make_document_embeddings

    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        raise SystemExit("DATABASE_URL is required in the repository-root .env file.")
    with psycopg.connect(database_url, row_factory=dict_row) as connection:
        connection.execute("SELECT pg_advisory_lock(%s, %s)", INGESTION_LOCK_KEY)
        connection.commit()
        print(make_document_embeddings(connection))


if __name__ == "__main__":
    main()
