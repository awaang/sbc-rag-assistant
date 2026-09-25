CREATE TABLE evaluation_runs (
    run_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    manifest_version TEXT NOT NULL,
    retrieval_method TEXT NOT NULL CHECK (retrieval_method IN ('bm25', 'semantic')),
    chunk_strategy TEXT NOT NULL CHECK (chunk_strategy IN ('fixed_size', 'section_aware')),
    top_k INTEGER NOT NULL CHECK (top_k > 0),
    question_count INTEGER NOT NULL CHECK (question_count >= 0),
    hit_count INTEGER NOT NULL CHECK (hit_count >= 0),
    mean_latency_ms DOUBLE PRECISION,
    mean_reciprocal_rank DOUBLE PRECISION,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE evaluation_results (
    result_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    run_id BIGINT NOT NULL REFERENCES evaluation_runs(run_id) ON DELETE CASCADE,
    question_id TEXT NOT NULL,
    question_type TEXT NOT NULL,
    hit BOOLEAN NOT NULL,
    reciprocal_rank DOUBLE PRECISION NOT NULL,
    latency_ms DOUBLE PRECISION NOT NULL,
    retrieved_chunk_ids BIGINT[] NOT NULL DEFAULT '{}'
);

CREATE INDEX evaluation_runs_created_idx ON evaluation_runs(created_at DESC);
CREATE INDEX evaluation_results_run_idx ON evaluation_results(run_id);
