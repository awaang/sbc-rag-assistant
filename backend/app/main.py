"""Minimal authenticated API scaffold for the SBC Assistant."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Annotated, Literal

import firebase_admin
from dotenv import load_dotenv
from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, UploadFile, status
from fastapi.middleware.cors import CORSMiddleware
from firebase_admin import auth, credentials
from pydantic import BaseModel, Field
import psycopg
from psycopg.rows import dict_row

from app.benefits import extract_candidates
from app.ingestion import parse_pdf

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
    allow_methods=["GET", "POST", "PATCH"],
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


def require_admin(user: Annotated[dict, Depends(require_user)]) -> dict:
    if user.get("admin") is not True:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access is required.")
    return user


def database_connection():
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        raise HTTPException(status_code=503, detail="Database is not configured.")
    try:
        with psycopg.connect(database_url, row_factory=dict_row) as connection:
            yield connection
    except psycopg.Error as exc:
        raise HTTPException(status_code=503, detail="Database request failed.") from exc


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


class BenefitReview(BaseModel):
    verification_status: Literal["pending_review", "verified", "missing", "ambiguous", "conflicting"]
    value_text: str | None = Field(default=None, max_length=4000)
    dimensions: dict[str, str] = Field(default_factory=dict)


class ExtractBenefitsRequest(BaseModel):
    document_id: int = Field(gt=0)


class DocumentReview(BaseModel):
    review_status: Literal["approved", "rejected"]


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


@app.get("/api/admin/benefits")
def list_benefits(
    _admin: Annotated[dict, Depends(require_admin)],
    connection: Annotated[psycopg.Connection, Depends(database_connection)],
    status_filter: str = "pending_review",
) -> list[dict]:
    allowed = {"pending_review", "verified", "missing", "ambiguous", "conflicting", "all"}
    if status_filter not in allowed:
        raise HTTPException(status_code=422, detail="Unknown benefit review status.")
    where = "" if status_filter == "all" else "WHERE b.verification_status = %s"
    params = () if status_filter == "all" else (status_filter,)
    rows = connection.execute(
        f"""SELECT b.benefit_id, b.plan_id, p.plan_name, d.document_id,
                   d.original_filename, d.corpus_status, b.category, b.value_text,
                   b.dimensions, b.source_page_id, pg.page_number, b.source_section,
                   b.verification_status
            FROM benefit_records b JOIN plans p USING (plan_id)
            JOIN documents d USING (document_id)
            LEFT JOIN document_pages pg ON pg.page_id = b.source_page_id
            {where} ORDER BY d.document_id, pg.page_number, b.benefit_id""", params
    ).fetchall()
    return [dict(row) for row in rows]


@app.post("/api/admin/benefits/extract")
def extract_document_benefits(
    request: ExtractBenefitsRequest,
    admin: Annotated[dict, Depends(require_admin)],
    connection: Annotated[psycopg.Connection, Depends(database_connection)],
) -> dict:
    document = connection.execute(
        "SELECT plan_id FROM documents WHERE document_id = %s", (request.document_id,)
    ).fetchone()
    if not document or document["plan_id"] is None:
        raise HTTPException(status_code=404, detail="Document or associated plan was not found.")
    pages = connection.execute(
        "SELECT page_id, page_number, section_heading, extracted_text AS text, tables_json FROM document_pages WHERE document_id = %s ORDER BY page_number",
        (request.document_id,),
    ).fetchall()
    if not pages:
        raise HTTPException(status_code=409, detail="The document has no parsed pages. Complete Phase 2 ingestion first.")
    extraction_pages = []
    for row in pages:
        page = dict(row)
        table_lines = []
        for table in page.pop("tables_json") or []:
            headers = table.get("headers", [])
            for cells in table.get("rows", []):
                table_lines.append(" | ".join(
                    f"{headers[index] if index < len(headers) and headers[index] else f'Column {index + 1}'}: {cell}"
                    for index, cell in enumerate(cells) if cell
                ))
        # Prefer table rows when a page has detected tables: pdfplumber's flat
        # text often interleaves columns and duplicates the same benefit row.
        page["text"] = "\n".join(table_lines) if table_lines else page["text"]
        extraction_pages.append(page)
    candidates = extract_candidates(extraction_pages)
    inserted = 0
    with connection.transaction():
        for candidate in candidates:
            page_id = next(page["page_id"] for page in pages if page["page_number"] == candidate.page_number)
            result = connection.execute(
                """INSERT INTO benefit_records
                   (plan_id, document_id, category, value_text, dimensions, source_page_id,
                   source_section, verification_status)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
                   ON CONFLICT (document_id, source_page_id, category, value_text) DO NOTHING""",
                (document["plan_id"], request.document_id, candidate.category,
                 candidate.value_text, psycopg.types.json.Jsonb(candidate.dimensions),
                 page_id, candidate.section, candidate.status),
            )
            inserted += result.rowcount
    return {"document_id": request.document_id, "candidates_created": inserted, "reviewer_uid": admin.get("uid")}


@app.get("/api/admin/documents")
def list_parsed_documents(
    _admin: Annotated[dict, Depends(require_admin)],
    connection: Annotated[psycopg.Connection, Depends(database_connection)],
) -> list[dict]:
    return [dict(row) for row in connection.execute(
        """SELECT d.document_id, d.original_filename, d.source_url, d.corpus_status, d.review_status,
                  d.ingestion_error, p.plan_name, p.insurer, p.plan_type, p.coverage_type,
                  p.plan_year, count(pg.page_id) AS parsed_pages
           FROM documents d LEFT JOIN plans p USING (plan_id)
           LEFT JOIN document_pages pg ON pg.document_id = d.document_id
           GROUP BY d.document_id, p.plan_name, p.insurer, p.plan_type, p.coverage_type, p.plan_year
           ORDER BY d.document_id"""
    ).fetchall()]


@app.post("/api/admin/documents", status_code=201)
def upload_document(
    admin: Annotated[dict, Depends(require_admin)],
    connection: Annotated[psycopg.Connection, Depends(database_connection)],
    file: UploadFile = File(...),
    insurer: str = Form(..., min_length=1, max_length=120),
    plan_name: str = Form(..., min_length=1, max_length=240),
    plan_type: Literal["hmo", "ppo", "hdhp", "pos", "other", "unknown"] = Form("unknown"),
    coverage_type: Literal["medical", "dental", "vision", "unknown"] = Form("medical"),
    plan_year: int | None = Form(None, ge=1900, le=2200),
    source_url: str | None = Form(None, max_length=2000),
) -> dict:
    """Store an uploaded candidate PDF durably; upload never verifies/approves it."""
    max_bytes = int(os.getenv("MAX_UPLOAD_BYTES", str(15 * 1024 * 1024)))
    filename = Path(file.filename or "upload.pdf").name[:255]
    if not filename.lower().endswith(".pdf") or file.content_type not in {"application/pdf", "application/octet-stream"}:
        raise HTTPException(status_code=415, detail="Upload a PDF file.")
    pdf_bytes = file.file.read(max_bytes + 1)
    file.file.close()
    if len(pdf_bytes) > max_bytes:
        raise HTTPException(status_code=413, detail=f"PDF exceeds the {max_bytes // (1024 * 1024)} MB upload limit.")
    if not pdf_bytes.startswith(b"%PDF-"):
        raise HTTPException(status_code=415, detail="The uploaded file does not have a valid PDF signature.")
    import hashlib
    digest = hashlib.sha256(pdf_bytes).hexdigest()
    existing = connection.execute("SELECT document_id FROM documents WHERE document_sha256 = %s", (digest,)).fetchone()
    if existing:
        raise HTTPException(status_code=409, detail=f"This PDF is already registered as document {existing['document_id']}.")
    with connection.transaction():
        plan = connection.execute(
            "INSERT INTO plans (insurer, plan_name, plan_type, coverage_type, plan_year) VALUES (%s,%s,%s,%s,%s) RETURNING plan_id",
            (insurer.strip(), plan_name.strip(), plan_type, coverage_type, plan_year),
        ).fetchone()
        row = connection.execute(
            """INSERT INTO documents
               (plan_id, original_filename, source_url, document_sha256, pdf_bytes,
                corpus_status, review_status, uploaded_by_firebase_uid)
               VALUES (%s,%s,%s,%s,%s,'candidate','uploaded',%s)
               RETURNING document_id, review_status, corpus_status""",
            (plan["plan_id"], filename, source_url or None, digest, pdf_bytes, admin.get("uid")),
        ).fetchone()
    return dict(row)


@app.get("/api/admin/documents/{document_id}")
def document_inspection(
    document_id: int,
    _admin: Annotated[dict, Depends(require_admin)],
    connection: Annotated[psycopg.Connection, Depends(database_connection)],
) -> dict:
    doc = connection.execute(
        """SELECT d.document_id, d.original_filename, d.corpus_status, d.review_status,
                  d.ingestion_error, p.plan_name, p.insurer, p.plan_type, p.coverage_type, p.plan_year
           FROM documents d LEFT JOIN plans p USING (plan_id) WHERE d.document_id = %s""",
        (document_id,),
    ).fetchone()
    if not doc:
        raise HTTPException(status_code=404, detail="Document was not found.")
    pages = connection.execute(
        """SELECT page_id, page_number, section_heading, extracted_text, tables_json, parse_status
           FROM document_pages WHERE document_id = %s ORDER BY page_number""", (document_id,)
    ).fetchall()
    chunks = connection.execute(
        """SELECT chunk_id, chunk_strategy, chunk_text, page_start, page_end, provenance
           FROM chunks WHERE document_id = %s ORDER BY chunk_strategy, chunk_id""", (document_id,)
    ).fetchall()
    return {"document": dict(doc), "pages": [dict(row) for row in pages], "chunks": [dict(row) for row in chunks]}


@app.patch("/api/admin/documents/{document_id}/review")
def review_document(
    document_id: int,
    review: DocumentReview,
    admin: Annotated[dict, Depends(require_admin)],
    connection: Annotated[psycopg.Connection, Depends(database_connection)],
) -> dict:
    if review.review_status == "approved":
        ready = connection.execute(
            "SELECT 1 FROM documents d WHERE d.document_id = %s AND d.review_status = 'needs_review' AND EXISTS (SELECT 1 FROM document_pages p WHERE p.document_id = d.document_id)",
            (document_id,),
        ).fetchone()
        if not ready:
            raise HTTPException(status_code=409, detail="Only successfully ingested documents awaiting review can be approved.")
    row = connection.execute(
        """UPDATE documents SET review_status = %s, reviewed_by_firebase_uid = %s, reviewed_at = now()
           WHERE document_id = %s AND review_status IN ('needs_review','approved','rejected')
           RETURNING document_id, corpus_status, review_status, reviewed_at""",
        (review.review_status, admin.get("uid"), document_id),
    ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Ingested document was not found.")
    return dict(row)


@app.post("/api/admin/documents/{document_id}/retry")
def retry_document_ingestion(
    document_id: int,
    _admin: Annotated[dict, Depends(require_admin)],
    connection: Annotated[psycopg.Connection, Depends(database_connection)],
) -> dict:
    row = connection.execute(
        """UPDATE documents SET review_status = 'uploaded', ingestion_error = NULL
           WHERE document_id = %s AND review_status = 'needs_review'
           RETURNING document_id, review_status""", (document_id,)
    ).fetchone()
    if not row:
        raise HTTPException(status_code=409, detail="Only a document awaiting review can be queued for re-ingestion.")
    return dict(row)


@app.patch("/api/admin/benefits/{benefit_id}")
def review_benefit(
    benefit_id: int,
    review: BenefitReview,
    admin: Annotated[dict, Depends(require_admin)],
    connection: Annotated[psycopg.Connection, Depends(database_connection)],
) -> dict:
    row = connection.execute(
        """UPDATE benefit_records SET value_text = %s, dimensions = %s,
                   verification_status = %s, reviewer_firebase_uid = %s, reviewed_at = now()
           WHERE benefit_id = %s RETURNING benefit_id, verification_status, value_text, dimensions""",
        (review.value_text, psycopg.types.json.Jsonb(review.dimensions),
         review.verification_status, admin.get("uid"), benefit_id),
    ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Benefit record was not found.")
    return dict(row)
