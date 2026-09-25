from contextlib import contextmanager

from fastapi.testclient import TestClient

from app.main import app, database_connection, require_user


class FakeResult:
    def __init__(self, row):
        self.row = row

    def fetchone(self):
        return self.row


class FakeConnection:
    @contextmanager
    def transaction(self):
        yield

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


def test_admin_upload_stays_candidate_until_review():
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


def test_admin_routes_reject_authenticated_non_admins():
    app.dependency_overrides[require_user] = lambda: {"uid": "member-uid", "admin": False}
    response = TestClient(app).get("/api/admin/documents")

    assert response.status_code == 403
