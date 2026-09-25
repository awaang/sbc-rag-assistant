"""Fetch uploaded PDFs from Neon and parse/chunk them on the local machine."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import re

import psycopg
from dotenv import load_dotenv
from psycopg.rows import dict_row

from app.ingestion import build_chunks, parse_pdf

load_dotenv(Path(__file__).resolve().parents[2] / ".env")


def _section_heading(text: str) -> str | None:
    headings: list[str] = []
    for line in text.splitlines():
        value = " ".join(line.split())
        if value and len(value) <= 120 and value.isupper() and not re.search(r"[.$%]", value):
            if value not in headings:
                headings.append(value)
    return headings[0] if len(headings) == 1 else None


def ingest_document(connection: psycopg.Connection, document: dict) -> dict:
    document_id = document["document_id"]
    connection.execute("UPDATE documents SET review_status = 'processing', ingestion_error = NULL WHERE document_id = %s", (document_id,))
    connection.commit()
    try:
        pages = parse_pdf(bytes(document["pdf_bytes"]))
        chunks = build_chunks(pages)
        issues = []
        for page in pages:
            if not page["text"].strip() and not page["tables"]:
                issues.append(f"Page {page['page_number']} contains no extractable text or tables (possibly scanned).")
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
                     psycopg.types.json.Jsonb(page["tables"]), "parsed" if readable else "needs_review"),
                )
            for strategy, strategy_chunks in chunks.items():
                for chunk in strategy_chunks:
                    connection.execute(
                        """INSERT INTO chunks
                           (document_id, chunk_strategy, strategy_version, chunk_text, page_start, page_end, provenance)
                           VALUES (%s,%s,1,%s,%s,%s,%s)""",
                        (document_id, strategy, chunk["text"], chunk["page_start"], chunk["page_end"],
                         psycopg.types.json.Jsonb(chunk["provenance"])),
                    )
            connection.execute(
                """UPDATE documents SET review_status = 'needs_review', ingestion_error = %s
                   WHERE document_id = %s""",
                ("\n".join(issues) or None, document_id),
            )
        return {"document_id": document_id, "pages": len(pages),
                "fixed_size_chunks": len(chunks["fixed_size"]),
                "section_aware_chunks": len(chunks["section_aware"]), "issues": issues}
    except Exception as exc:
        message = f"{type(exc).__name__}: {exc}"[:2000]
        connection.execute(
            "UPDATE documents SET review_status = 'needs_review', ingestion_error = %s WHERE document_id = %s",
            (message, document_id),
        )
        connection.commit()
        return {"document_id": document_id, "error": message}


def main() -> None:
    parser = argparse.ArgumentParser(description="Ingest uploaded documents from Neon.")
    parser.add_argument("--reprocess-id", type=int, help="Reparse one reviewed document and require approval again.")
    args = parser.parse_args()
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        raise SystemExit("DATABASE_URL is required in the repository-root .env file.")
    with psycopg.connect(database_url, row_factory=dict_row) as connection:
        if args.reprocess_id is None:
            pending = connection.execute(
                """SELECT document_id, pdf_bytes FROM documents WHERE review_status = 'uploaded'
                   ORDER BY document_id"""
            ).fetchall()
        else:
            pending = connection.execute(
                """SELECT document_id, pdf_bytes FROM documents
                   WHERE document_id = %s AND review_status IN ('approved', 'needs_review')""",
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
        print(make_document_embeddings(connection))


if __name__ == "__main__":
    main()
