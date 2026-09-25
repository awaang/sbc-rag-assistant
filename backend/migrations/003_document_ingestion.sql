ALTER TABLE document_pages
    ADD COLUMN tables_json JSONB NOT NULL DEFAULT '[]'::jsonb;

ALTER TABLE documents
    ADD COLUMN ingestion_error TEXT;

ALTER TABLE documents
    ADD COLUMN reviewed_by_firebase_uid TEXT,
    ADD COLUMN reviewed_at TIMESTAMPTZ;

CREATE INDEX document_pages_document_page_idx
    ON document_pages (document_id, page_number);
