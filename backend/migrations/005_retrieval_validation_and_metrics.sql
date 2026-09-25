ALTER TABLE chunk_embeddings
    ADD COLUMN model_fingerprint TEXT;

ALTER TABLE evaluation_runs
    ADD COLUMN manifest_sha256 TEXT,
    ADD COLUMN embedding_model_name TEXT,
    ADD COLUMN embedding_model_version TEXT,
    ADD COLUMN embedding_model_fingerprint TEXT,
    ADD COLUMN model_initialization_ms DOUBLE PRECISION NOT NULL DEFAULT 0,
    ADD COLUMN corpus_snapshot JSONB NOT NULL DEFAULT '{}'::jsonb,
    ADD COLUMN chunk_strategy_version INTEGER NOT NULL DEFAULT 1,
    ADD COLUMN mean_corpus_load_ms DOUBLE PRECISION NOT NULL DEFAULT 0,
    ADD COLUMN mean_embedding_load_ms DOUBLE PRECISION NOT NULL DEFAULT 0,
    ADD COLUMN mean_index_build_ms DOUBLE PRECISION NOT NULL DEFAULT 0,
    ADD COLUMN mean_query_embedding_ms DOUBLE PRECISION NOT NULL DEFAULT 0,
    ADD COLUMN mean_model_load_ms DOUBLE PRECISION NOT NULL DEFAULT 0,
    ADD COLUMN mean_search_ms DOUBLE PRECISION NOT NULL DEFAULT 0;

ALTER TABLE evaluation_results
    ADD COLUMN corpus_load_ms DOUBLE PRECISION NOT NULL DEFAULT 0,
    ADD COLUMN embedding_load_ms DOUBLE PRECISION NOT NULL DEFAULT 0,
    ADD COLUMN index_build_ms DOUBLE PRECISION NOT NULL DEFAULT 0,
    ADD COLUMN query_embedding_ms DOUBLE PRECISION NOT NULL DEFAULT 0,
    ADD COLUMN model_load_ms DOUBLE PRECISION NOT NULL DEFAULT 0,
    ADD COLUMN search_ms DOUBLE PRECISION NOT NULL DEFAULT 0;
