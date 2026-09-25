from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

from app import main
from app.main import app


class EmptyResult:
    def fetchall(self):
        return []


class EmptyConnection:
    def execute(self, _sql, _params=()):
        return EmptyResult()


@pytest.fixture(autouse=True)
def clean_dependency_overrides():
    app.dependency_overrides.clear()
    yield
    app.dependency_overrides.clear()


@pytest.fixture
def configured_firebase(monkeypatch):
    monkeypatch.setattr(main, "firebase_is_configured", lambda: True)
    verifier = Mock(return_value={"uid": "member-uid", "admin": False})
    monkeypatch.setattr(main.auth, "verify_id_token", verifier)
    return verifier


def test_protected_route_rejects_missing_bearer_token(configured_firebase):
    response = TestClient(app).get("/api/plans")

    assert response.status_code == 401
    assert response.json()["detail"] == "Sign in to continue."
    configured_firebase.assert_not_called()


@pytest.mark.parametrize("authorization", ["Basic credentials", "Bearer   "])
def test_protected_route_rejects_malformed_bearer_header(configured_firebase, authorization):
    response = TestClient(app).get("/api/plans", headers={"Authorization": authorization})

    assert response.status_code == 401
    configured_firebase.assert_not_called()


def test_protected_route_rejects_invalid_firebase_token(configured_firebase):
    configured_firebase.side_effect = ValueError("invalid token")

    response = TestClient(app).get(
        "/api/plans", headers={"Authorization": "Bearer invalid-token"}
    )

    assert response.status_code == 401
    assert response.json()["detail"] == "Your session is invalid or expired."
    configured_firebase.assert_called_once_with("invalid-token", check_revoked=True)


def test_protected_route_accepts_verified_firebase_token(configured_firebase):
    app.dependency_overrides[main.database_connection] = lambda: EmptyConnection()

    response = TestClient(app).get(
        "/api/plans", headers={"Authorization": "Bearer valid-token"}
    )

    assert response.status_code == 200
    assert response.json() == []
    configured_firebase.assert_called_once_with("valid-token", check_revoked=True)


def test_admin_route_rejects_verified_non_admin_token(configured_firebase):
    response = TestClient(app).get(
        "/api/admin/documents", headers={"Authorization": "Bearer valid-token"}
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "Admin access is required."
    configured_firebase.assert_called_once_with("valid-token", check_revoked=True)


def test_protected_route_fails_closed_when_firebase_is_unconfigured(monkeypatch):
    verifier = Mock()
    monkeypatch.setattr(main, "firebase_is_configured", lambda: False)
    monkeypatch.setattr(main.auth, "verify_id_token", verifier)

    response = TestClient(app).get(
        "/api/plans", headers={"Authorization": "Bearer valid-token"}
    )

    assert response.status_code == 503
    assert response.json()["detail"] == "Firebase authentication is not configured on the API."
    verifier.assert_not_called()
