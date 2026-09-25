CREATE TABLE plans (
    plan_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    insurer TEXT NOT NULL,
    plan_name TEXT NOT NULL,
    plan_type TEXT NOT NULL DEFAULT 'unknown'
        CHECK (plan_type IN ('hmo', 'ppo', 'hdhp', 'pos', 'other', 'unknown')),
    coverage_type TEXT NOT NULL DEFAULT 'unknown'
        CHECK (coverage_type IN ('medical', 'dental', 'vision', 'unknown')),
    plan_year INTEGER,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE documents (
    document_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    plan_id BIGINT REFERENCES plans(plan_id) ON DELETE SET NULL,
    original_filename TEXT NOT NULL,
    source_url TEXT,
    document_sha256 CHAR(64),
    pdf_bytes BYTEA,
    corpus_status TEXT NOT NULL DEFAULT 'candidate'
        CHECK (corpus_status IN ('candidate', 'verified_sbc', 'ineligible')),
    review_status TEXT NOT NULL DEFAULT 'uploaded'
        CHECK (review_status IN ('uploaded', 'processing', 'needs_review', 'approved', 'rejected')),
    uploaded_by_firebase_uid TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE document_pages (
    page_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    document_id BIGINT NOT NULL REFERENCES documents(document_id) ON DELETE CASCADE,
    page_number INTEGER NOT NULL CHECK (page_number > 0),
    section_heading TEXT,
    extracted_text TEXT NOT NULL DEFAULT '',
    parse_status TEXT NOT NULL DEFAULT 'pending'
        CHECK (parse_status IN ('pending', 'parsed', 'needs_review', 'failed')),
    UNIQUE (document_id, page_number)
);

CREATE TABLE chunks (
    chunk_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    document_id BIGINT NOT NULL REFERENCES documents(document_id) ON DELETE CASCADE,
    chunk_strategy TEXT NOT NULL
        CHECK (chunk_strategy IN ('fixed_size', 'section_aware')),
    strategy_version INTEGER NOT NULL DEFAULT 1 CHECK (strategy_version > 0),
    chunk_text TEXT NOT NULL,
    page_start INTEGER,
    page_end INTEGER,
    provenance JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (page_start IS NULL OR page_start > 0),
    CHECK (page_end IS NULL OR page_end >= page_start)
);

CREATE TABLE benefit_records (
    benefit_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    plan_id BIGINT NOT NULL REFERENCES plans(plan_id) ON DELETE CASCADE,
    document_id BIGINT NOT NULL REFERENCES documents(document_id) ON DELETE CASCADE,
    category TEXT NOT NULL
        CHECK (category IN ('deductible', 'er_cost_sharing', 'copay', 'out_of_pocket_maximum', 'other')),
    value_text TEXT,
    dimensions JSONB NOT NULL DEFAULT '{}'::jsonb,
    source_page_id BIGINT REFERENCES document_pages(page_id) ON DELETE SET NULL,
    source_section TEXT,
    verification_status TEXT NOT NULL DEFAULT 'pending_review'
        CHECK (verification_status IN ('pending_review', 'verified', 'missing', 'ambiguous', 'conflicting')),
    reviewer_firebase_uid TEXT,
    reviewed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE chunk_embeddings (
    embedding_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    chunk_id BIGINT NOT NULL REFERENCES chunks(chunk_id) ON DELETE CASCADE,
    model_name TEXT NOT NULL,
    model_version TEXT NOT NULL,
    embedding_values DOUBLE PRECISION[] NOT NULL CHECK (cardinality(embedding_values) > 0),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (chunk_id, model_name, model_version)
);

CREATE INDEX documents_plan_id_idx ON documents(plan_id);
CREATE INDEX documents_review_status_idx ON documents(review_status);
CREATE INDEX chunks_document_strategy_idx ON chunks(document_id, chunk_strategy, strategy_version);
CREATE INDEX benefit_records_plan_category_idx ON benefit_records(plan_id, category, verification_status);
CREATE INDEX chunk_embeddings_chunk_id_idx ON chunk_embeddings(chunk_id);
