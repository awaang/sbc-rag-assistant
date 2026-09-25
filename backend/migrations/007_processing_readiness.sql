ALTER TABLE documents DROP CONSTRAINT documents_review_status_check;
ALTER TABLE documents ADD CONSTRAINT documents_review_status_check
    CHECK (review_status IN ('uploaded', 'processing', 'needs_review', 'approved',
                            'rejected', 'ready', 'ready_with_warnings', 'failed'));
ALTER TABLE documents
    ADD COLUMN processing_stages JSONB NOT NULL DEFAULT '{}'::jsonb,
    ADD COLUMN processing_warnings JSONB NOT NULL DEFAULT '[]'::jsonb;
