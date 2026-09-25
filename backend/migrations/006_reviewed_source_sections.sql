-- Existing section labels were copied from a page-wide heading and need review.
ALTER TABLE benefit_records
    ADD COLUMN source_section_verified BOOLEAN NOT NULL DEFAULT FALSE;
