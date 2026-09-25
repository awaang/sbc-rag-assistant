ALTER TABLE documents
    ADD COLUMN ingestion_queued_at TIMESTAMPTZ,
    ADD COLUMN ingestion_attempts INTEGER NOT NULL DEFAULT 0
        CHECK (ingestion_attempts >= 0);

CREATE INDEX documents_ingestion_queue_idx
    ON documents (ingestion_queued_at, document_id)
    WHERE ingestion_queued_at IS NOT NULL;
