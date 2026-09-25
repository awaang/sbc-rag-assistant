"""Minimal authenticated API scaffold for the SBC Assistant."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Annotated, Literal

import firebase_admin
from dotenv import load_dotenv
from fastapi import Depends, FastAPI, Header, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from firebase_admin import auth, credentials
from pydantic import BaseModel, Field

load_dotenv(Path(__file__).resolve().parents[2] / ".env")

app = FastAPI(title="SBC Assistant API", version="0.1.0")
origins = [
    origin.strip()
    for origin in os.getenv("FRONTEND_ORIGIN", "http://localhost:5173").split(",")
    if origin.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["Authorization", "Content-Type"],
)


def firebase_is_configured() -> bool:
    if not os.getenv("FIREBASE_PROJECT_ID"):
        return False
    try:
        firebase_admin.get_app()
    except ValueError:
        credential_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
        credential = credentials.Certificate(credential_path) if credential_path else credentials.ApplicationDefault()
        firebase_admin.initialize_app(
            credential,
            {"projectId": os.environ["FIREBASE_PROJECT_ID"]},
        )
    return True


def require_user(authorization: Annotated[str | None, Header()] = None) -> dict:
    """Verify a Firebase ID token on every protected request; fail closed."""
    if not firebase_is_configured():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Firebase authentication is not configured on the API.",
        )
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Sign in to continue.")
    token = authorization.split(" ", 1)[1].strip()
    try:
        return auth.verify_id_token(token, check_revoked=True)
    except Exception as exc:  # Firebase SDK raises several token-specific exception types.
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Your session is invalid or expired.") from exc


class ChatRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)


class Citation(BaseModel):
    plan: str
    section: str
    page: int | None = None


class ChatResponse(BaseModel):
    status: Literal["answered", "insufficient_evidence", "clarification_needed"]
    answer: str
    citations: list[Citation]
    debug: dict[str, str]


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "sbc-assistant-api"}


@app.post("/api/chat", response_model=ChatResponse)
def chat(_user: Annotated[dict, Depends(require_user)], request: ChatRequest) -> ChatResponse:
    """Return a safe placeholder until verified documents and retrieval are implemented."""
    _ = request
    return ChatResponse(
        status="insufficient_evidence",
        answer=(
            "I can’t establish an answer from verified SBC documents yet. "
            "The supplied PDFs are candidate documents and have not been approved as the answer corpus."
        ),
        citations=[],
        debug={
            "evidence_path": "not_configured",
            "corpus": "no verified SBCs loaded",
            "answer_mode": "deterministic placeholder; no model call",
        },
    )
