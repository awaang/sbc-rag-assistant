-- Keep repeated candidate extraction idempotent at the source row level.
CREATE UNIQUE INDEX benefit_records_source_candidate_idx
    ON benefit_records (document_id, source_page_id, category, value_text);

CREATE INDEX benefit_records_reviewed_at_idx
    ON benefit_records (verification_status, reviewed_at);
