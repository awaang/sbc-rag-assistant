"""Apply ordered SQL migrations to the configured Neon/Postgres database."""

from __future__ import annotations

import os
from pathlib import Path

import psycopg
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[3] / ".env")

MIGRATIONS_DIR = Path(__file__).resolve().parents[2] / "migrations"


def apply_migrations() -> None:
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        raise SystemExit("DATABASE_URL is required. Set it in the repository-root .env file.")

    with psycopg.connect(database_url) as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version TEXT PRIMARY KEY,
                applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """
        )
        connection.commit()
        applied = {
            row[0]
            for row in connection.execute("SELECT version FROM schema_migrations").fetchall()
        }

        for migration in sorted(MIGRATIONS_DIR.glob("*.sql")):
            if migration.stem in applied:
                continue
            sql = migration.read_text(encoding="utf-8")
            with connection.transaction():
                connection.execute(sql)
                connection.execute(
                    "INSERT INTO schema_migrations (version) VALUES (%s)",
                    (migration.stem,),
                )
            print(f"Applied {migration.name}")


if __name__ == "__main__":
    apply_migrations()
