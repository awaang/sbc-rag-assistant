ALTER TABLE evaluation_runs
    DROP CONSTRAINT evaluation_runs_retrieval_method_check;

ALTER TABLE evaluation_runs
    ADD CONSTRAINT evaluation_runs_retrieval_method_check
        CHECK (retrieval_method IN ('bm25', 'semantic', 'hybrid'));
