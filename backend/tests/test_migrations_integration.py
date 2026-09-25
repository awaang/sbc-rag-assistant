"""Optional PostgreSQL integration check for the complete migration chain.

Set TEST_DATABASE_URL to a disposable PostgreSQL database to enable this test.
All migration objects are created in a temporary schema and rolled back.
"""

from __future__ import annotations

import os
from pathlib import Path
import uuid

import psycopg
import pytest


@pytest.mark.skipif(not os.getenv("TEST_DATABASE_URL"),
                    reason="set TEST_DATABASE_URL to a disposable PostgreSQL database")
def test_all_migrations_create_phase4_schema_and_support_evaluation_queries():
    schema = f"phase4_test_{uuid.uuid4().hex}"
    migrations_dir = Path(__file__).resolve().parents[1] / "migrations"

    with psycopg.connect(os.environ["TEST_DATABASE_URL"]) as connection:
        with connection.transaction():
            connection.execute(psycopg.sql.SQL("CREATE SCHEMA {}").format(psycopg.sql.Identifier(schema)))
            connection.execute(psycopg.sql.SQL("SET LOCAL search_path TO {}").format(psycopg.sql.Identifier(schema)))
            for migration in sorted(migrations_dir.glob("*.sql")):
                connection.execute(migration.read_text(encoding="utf-8"))

            run_columns = {row[0] for row in connection.execute(
                "SELECT column_name FROM information_schema.columns WHERE table_schema = %s AND table_name = 'evaluation_runs'",
                (schema,),
            ).fetchall()}
            result_columns = {row[0] for row in connection.execute(
                "SELECT column_name FROM information_schema.columns WHERE table_schema = %s AND table_name = 'evaluation_results'",
                (schema,),
            ).fetchall()}
            embedding_columns = {row[0] for row in connection.execute(
                "SELECT column_name FROM information_schema.columns WHERE table_schema = %s AND table_name = 'chunk_embeddings'",
                (schema,),
            ).fetchall()}

            assert {"manifest_sha256", "corpus_snapshot", "embedding_model_fingerprint",
                    "mean_index_build_ms", "chunk_strategy_version"} <= run_columns
            assert {"retrieved_chunk_ids", "query_embedding_ms", "search_ms"} <= result_columns
            assert {"embedding_values", "model_fingerprint"} <= embedding_columns

            # Exercise the joins and fields used by approved-chunk retrieval.
            connection.execute(
                """INSERT INTO plans (insurer, plan_name) VALUES ('Test', 'Plan')"""
            )
            connection.execute(
                """INSERT INTO documents (plan_id, original_filename, review_status)
                   SELECT plan_id, 'plan.pdf', 'approved' FROM plans"""
            )
            connection.execute(
                """INSERT INTO chunks (document_id, chunk_strategy, chunk_text, provenance)
                   SELECT document_id, 'fixed_size', 'deductible', '{\"units\":[]}'::jsonb FROM documents"""
            )
            found = connection.execute(
                """SELECT c.chunk_id FROM chunks c JOIN documents d USING (document_id)
                   WHERE d.review_status = 'approved' AND c.chunk_strategy = %s
                     AND c.strategy_version = %s""", ("fixed_size", 1),
            ).fetchone()
            assert found is not None
