from contextlib import contextmanager

from app import pipeline
from app.benefits import BenefitCandidate
from app.main import document_inspection


class Result:
    def __init__(self, rows):
        self.rows = rows

    def fetchall(self):
        return self.rows

    def fetchone(self):
        return self.rows[0] if self.rows else None


class Connection:
    def __init__(self, counts=None):
        self.counts = counts or []
        self.updates = []

    @contextmanager
    def transaction(self):
        yield

    def commit(self):
        pass

    def rollback(self):
        pass

    def execute(self, sql, params=None):
        if "UPDATE documents SET processing_stages" in sql:
            self.updates.append(params)
            return Result([])
        if "FROM document_pages WHERE document_id" in sql:
            return Result([{"page_id": 10, "page_number": 1, "section_heading": "PLAN COSTS",
                            "text": "Deductible: $500", "tables_json": []}])
        if "INSERT INTO benefit_records" in sql:
            return Result([])
        if "array_agg(e.embedding_values)" in sql:
            return Result(self.counts)
        raise AssertionError(sql)


def _counts():
    return [{"chunk_strategy": strategy, "total": 1, "embedded": 1, "vectors": [[0.6, 0.8]]}
            for strategy in ("fixed_size", "section_aware")]


def _document():
    return {"document_id": 2, "plan_id": 3, "plan_name": "Basic", "insurer": "Alpha",
            "pdf_bytes": b"%PDF-example"}


def test_readiness_requires_every_stage_and_both_embedding_strategies():
    stages = dict.fromkeys(("parsing", "chunking", "benefit_extraction", "embedding"), "completed")
    counts = {row["chunk_strategy"]: row for row in _counts()}
    assert pipeline.readiness_status(stages, [], counts) == "ready"
    assert pipeline.readiness_status(stages, ["Page 2 failed"], counts) == "ready_with_warnings"
    assert pipeline.readiness_status({**stages, "embedding": "pending"}, [], counts) == "needs_review"
    assert pipeline.readiness_status(stages, [], {"fixed_size": counts["fixed_size"]}) == "failed"


def test_pipeline_preserves_warning_and_promotes_usable_evidence(monkeypatch):
    connection = Connection(_counts())
    monkeypatch.setattr(pipeline, "ingest_document", lambda *_: {"issues": ["Page 2 table extraction failed"]})
    monkeypatch.setattr(pipeline, "extract_candidates", lambda *_: [
        BenefitCandidate("deductible", "Deductible: $500", 1, "PLAN COSTS", {})])
    monkeypatch.setattr(pipeline, "make_document_embeddings", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(pipeline, "model_fingerprint", lambda: "model-hash")
    monkeypatch.setattr(pipeline, "model_dimension", lambda: 2)

    result = pipeline.process_document(connection, _document())

    assert result["status"] == "ready_with_warnings"
    assert result["candidates"] == 1
    assert connection.updates[-1][2] == "ready_with_warnings"
    assert connection.updates[-1][0].obj["embedding"] == "completed"

    uploaded = pipeline.process_document(
        connection, {**_document(), "uploaded_by_firebase_uid": "admin-uid"}
    )
    assert uploaded["status"] == "approved"
    assert uploaded["warnings"] == ["Page 2 table extraction failed"]
    assert connection.updates[-1][2] == "approved"


def test_pipeline_keeps_critical_failures_unavailable(monkeypatch):
    connection = Connection()
    monkeypatch.setattr(pipeline, "ingest_document", lambda *_: {"error": "Unreadable PDF"})
    assert pipeline.process_document(connection, _document())["status"] == "failed"

    no_identity = {**_document(), "plan_name": ""}
    assert pipeline.process_document(connection, no_identity)["status"] == "failed"
    assert connection.updates[-1][2] == "failed"


def test_pipeline_reports_embedding_failure_stage(monkeypatch):
    connection = Connection([_counts()[0]])
    monkeypatch.setattr(pipeline, "ingest_document", lambda *_: {"issues": []})
    monkeypatch.setattr(pipeline, "extract_candidates", lambda *_: [])
    monkeypatch.setattr(pipeline, "make_document_embeddings", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(pipeline, "model_fingerprint", lambda: "model-hash")
    monkeypatch.setattr(pipeline, "model_dimension", lambda: 2)

    result = pipeline.process_document(connection, _document())

    assert result["status"] == "failed"
    assert result["stages"]["embedding"] == "failed"
    assert connection.updates[-1][2] == "failed"


def test_pipeline_rejects_vectors_with_wrong_model_dimension(monkeypatch):
    connection = Connection(_counts())
    monkeypatch.setattr(pipeline, "ingest_document", lambda *_: {"issues": []})
    monkeypatch.setattr(pipeline, "extract_candidates", lambda *_: [])
    monkeypatch.setattr(pipeline, "make_document_embeddings", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(pipeline, "model_fingerprint", lambda: "model-hash")
    monkeypatch.setattr(pipeline, "model_dimension", lambda: 3)

    result = pipeline.process_document(connection, _document())

    assert result["status"] == "failed"
    assert "invalid vectors" in result["error"]


def test_admin_inspection_exposes_stages_and_warnings():
    class InspectionConnection:
        def execute(self, sql, _params=None):
            if "FROM documents d LEFT JOIN plans" in sql:
                return Result([{"document_id": 2, "processing_stages": {"embedding": "failed"},
                                "processing_warnings": ["Page 2 table extraction failed"],
                                "ingestion_error": "Embedding failed"}])
            return Result([])

    result = document_inspection(2, {"uid": "admin", "admin": True}, InspectionConnection())
    assert result["document"]["processing_stages"]["embedding"] == "failed"
    assert result["document"]["processing_warnings"] == ["Page 2 table extraction failed"]
