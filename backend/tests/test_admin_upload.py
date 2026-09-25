from contextlib import contextmanager

from fastapi.testclient import TestClient

from app.main import BenefitReview, DocumentReview, app, database_connection, require_user, review_benefit, review_document
from fastapi import HTTPException
import pytest


class FakeResult:
    def __init__(self, row):
        self.row = row

    def fetchone(self):
        return self.row


class FakeConnection:
    @contextmanager
    def transaction(self):
        yield

    def commit(self):
        pass

    def execute(self, sql, _params=None):
        if "SELECT document_id FROM documents" in sql:
            return FakeResult(None)
        if "INSERT INTO plans" in sql:
            return FakeResult({"plan_id": 1})
        if "INSERT INTO documents" in sql:
            return FakeResult({
                "document_id": 12,
                "review_status": "uploaded",
                "corpus_status": "candidate",
            })
        raise AssertionError(f"Unexpected SQL: {sql}")


def teardown_function():
    app.dependency_overrides.clear()


def test_admin_upload_queues_candidate_for_automatic_processing(monkeypatch):
    scheduled = []
    monkeypatch.setattr("app.main.drain_pending_documents", lambda: scheduled.append(True))
    app.dependency_overrides[require_user] = lambda: {"uid": "admin-uid", "admin": True}
    app.dependency_overrides[database_connection] = lambda: FakeConnection()
    client = TestClient(app)

    response = client.post(
        "/api/admin/documents",
        files={"file": ("plan.pdf", b"%PDF-1.7\nexample", "application/pdf")},
        data={"insurer": "Example", "plan_name": "Test plan", "plan_type": "hmo",
              "coverage_type": "medical"},
    )

    assert response.status_code == 201
    assert response.json()["review_status"] == "uploaded"
    assert response.json()["corpus_status"] == "candidate"
    assert scheduled == [True]


def test_admin_routes_reject_authenticated_non_admins():
    app.dependency_overrides[require_user] = lambda: {"uid": "member-uid", "admin": False}
    response = TestClient(app).get("/api/admin/documents")

    assert response.status_code == 403


def test_retry_requeues_and_starts_automatic_processing(monkeypatch):
    scheduled = []
    monkeypatch.setattr("app.main.drain_pending_documents", lambda: scheduled.append(True))

    class RetryConnection(FakeConnection):
        def execute(self, sql, _params=None):
            assert "UPDATE documents SET review_status = 'uploaded'" in sql
            assert "ingestion_queued_at = now(), ingestion_attempts = 0" in sql
            return FakeResult({"document_id": 12, "review_status": "uploaded"})

    app.dependency_overrides[require_user] = lambda: {"uid": "admin-uid", "admin": True}
    app.dependency_overrides[database_connection] = lambda: RetryConnection()

    response = TestClient(app).post("/api/admin/documents/12/retry")

    assert response.status_code == 200
    assert scheduled == [True]


def test_delete_removes_document_and_unused_plan():
    statements = []

    class DeleteConnection(FakeConnection):
        def execute(self, sql, params=None):
            statements.append(sql)
            if "SELECT plan_id, ingestion_queued_at" in sql:
                return FakeResult({"plan_id": 3, "ingestion_queued_at": None, "review_status": "ready"})
            return FakeResult(None)

    app.dependency_overrides[require_user] = lambda: {"uid": "admin-uid", "admin": True}
    app.dependency_overrides[database_connection] = lambda: DeleteConnection()

    response = TestClient(app).delete("/api/admin/documents/12")

    assert response.status_code == 200
    assert any("DELETE FROM documents WHERE document_id" in sql for sql in statements)
    assert any("DELETE FROM plans" in sql and "NOT EXISTS" in sql for sql in statements)


def test_delete_refuses_document_still_processing():
    class ProcessingConnection(FakeConnection):
        def execute(self, sql, params=None):
            assert "DELETE" not in sql
            return FakeResult({"plan_id": 3, "ingestion_queued_at": "2026-09-25T00:00:00Z", "review_status": "processing"})

    app.dependency_overrides[require_user] = lambda: {"uid": "admin-uid", "admin": True}
    app.dependency_overrides[database_connection] = lambda: ProcessingConnection()

    response = TestClient(app).delete("/api/admin/documents/12")

    assert response.status_code == 409


def test_delete_rejects_non_admins():
    app.dependency_overrides[require_user] = lambda: {"uid": "member-uid", "admin": False}

    response = TestClient(app).delete("/api/admin/documents/12")

    assert response.status_code == 403


def test_verifying_benefit_requires_confirmed_section():
    with pytest.raises(HTTPException) as error:
        review_benefit(1, BenefitReview(verification_status="verified", value_text="Deductible: $500"),
                       {"uid": "admin-uid"}, FakeConnection())
    assert error.value.status_code == 422


def test_explicit_document_verification_requires_completed_processing():
    class IncompleteConnection:
        def execute(self, sql, _params=None):
            assert "processing_stages->>'embedding'" in sql
            return FakeResult(None)

    with pytest.raises(HTTPException) as error:
        review_document(12, DocumentReview(review_status="approved"),
                        {"uid": "admin-uid"}, IncompleteConnection())
    assert error.value.status_code == 409
