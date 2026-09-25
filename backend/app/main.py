"""Minimal authenticated API scaffold for the SBC Assistant."""

from __future__ import annotations

import os
import json
import hashlib
import time
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

load_dotenv(Path(__file__).resolve().parents[2] / ".env")

from app.benefits import extract_candidates
from app.ingestion import parse_pdf
from app.retrieval import EmbeddingDataError, MODEL_NAME, MODEL_VERSION, model_fingerprint, retrieve

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


class RetrievalRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    method: Literal["bm25", "semantic"]
    chunk_strategy: Literal["fixed_size", "section_aware"]
    strategy_version: int = Field(default=1, ge=1)
    top_k: int = Field(default=5, ge=1, le=20)
    plan_id: int | None = Field(default=None, gt=0)
    document_id: int | None = Field(default=None, gt=0)
    section: str | None = Field(default=None, max_length=200)


class EvaluationQuestion(BaseModel):
    question_id: str
    question: str
    question_type: str
    expected_answer: str
    expected_document_ids: list[int] = Field(min_length=1)
    expected_pages: list[int] = Field(default_factory=list)


def run_retrieval(connection, request: RetrievalRequest) -> dict:
    try:
        result = retrieve(connection, request.question, request.method,
                          request.chunk_strategy, request.top_k, request.strategy_version, request.plan_id,
                          request.document_id, request.section)
    except EmbeddingDataError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except (ImportError, OSError) as exc:
        raise HTTPException(status_code=503, detail=f"Retrieval dependency/model unavailable: {type(exc).__name__}.") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if request.method == "semantic" and result.get("index_status") == "no_approved_embeddings":
        result["index_status"] = "no_approved_embeddings; run python -m app.embed locally after document approval"
    return result


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "sbc-assistant-api"}


@app.post("/api/admin/retrieval/search")
def retrieval_search(
    request: RetrievalRequest,
    _admin: Annotated[dict, Depends(require_admin)],
    connection: Annotated[psycopg.Connection, Depends(database_connection)],
) -> dict:
    result = run_retrieval(connection, request)
    # Internal plan/document identifiers and score traces are admin-only.
    return {**result, "model_name": MODEL_NAME, "model_version": MODEL_VERSION}


@app.get("/api/admin/evaluation")
def get_evaluation(
    _admin: Annotated[dict, Depends(require_admin)],
    connection: Annotated[psycopg.Connection, Depends(database_connection)],
) -> dict:
    manifest_path = Path(__file__).resolve().parents[2] / "evaluation" / "questions.json"
    try:
        manifest_bytes = manifest_path.read_bytes()
        manifest = json.loads(manifest_bytes)
    except (OSError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=503, detail="Evaluation manifest is unavailable or invalid.") from exc
    runs = connection.execute(
        """SELECT run_id, manifest_version, retrieval_method, chunk_strategy,
                  manifest_sha256, chunk_strategy_version, top_k, question_count, hit_count,
                  mean_latency_ms, mean_reciprocal_rank, embedding_model_name,
                  embedding_model_version, embedding_model_fingerprint,
                  corpus_snapshot, model_initialization_ms, mean_corpus_load_ms,
                  mean_embedding_load_ms, mean_index_build_ms, mean_query_embedding_ms,
                  mean_model_load_ms, mean_search_ms, created_at
           FROM evaluation_runs ORDER BY created_at DESC LIMIT 20"""
    ).fetchall()
    return {"manifest_version": manifest.get("manifest_version"),
            "manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
            "corpus": manifest.get("corpus"), "question_count": len(manifest.get("questions", [])),
            "runs": [dict(row) for row in runs]}


@app.post("/api/admin/evaluation/run")
def run_evaluation(
    _admin: Annotated[dict, Depends(require_admin)],
    connection: Annotated[psycopg.Connection, Depends(database_connection)],
    top_k: int = 5,
    method: Literal["all", "bm25", "semantic"] = "all",
) -> dict:
    if not 1 <= top_k <= 20:
        raise HTTPException(status_code=422, detail="top_k must be between 1 and 20.")
    manifest_path = Path(__file__).resolve().parents[2] / "evaluation" / "questions.json"
    try:
        manifest_bytes = manifest_path.read_bytes()
        manifest = json.loads(manifest_bytes)
        questions = [EvaluationQuestion.model_validate(item) for item in manifest.get("questions", [])]
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        raise HTTPException(status_code=503, detail="Evaluation manifest is unavailable or invalid.") from exc
    if not questions:
        raise HTTPException(status_code=409, detail="Add manually checked questions and evidence labels to evaluation/questions.json first.")
    manifest_sha256 = hashlib.sha256(manifest_bytes).hexdigest()
    strategy_version = 1
    readiness = connection.execute(
        """SELECT c.chunk_strategy, count(*) AS chunk_count
           FROM chunks c JOIN documents d USING (document_id)
           WHERE d.review_status = 'approved' AND c.strategy_version = %s
           GROUP BY c.chunk_strategy""", (strategy_version,)
    ).fetchall()
    counts = {row["chunk_strategy"]: row["chunk_count"] for row in readiness}
    if any(counts.get(strategy, 0) == 0 for strategy in ("fixed_size", "section_aware")):
        raise HTTPException(status_code=409, detail="Approved strategy-version-1 chunks must exist for both chunk strategies before evaluation.")
    methods = ("bm25", "semantic") if method == "all" else (method,)
    initialization_ms = 0.0
    fingerprint = None
    if "semantic" in methods:
        model_init_start = time.perf_counter()
        try:
            fingerprint = model_fingerprint()
        except (ImportError, OSError) as exc:
            raise HTTPException(status_code=503, detail="Semantic model is unavailable; BM25-only evaluation remains available with method=bm25.") from exc
        initialization_ms = (time.perf_counter() - model_init_start) * 1000
        embeddings = connection.execute(
            """SELECT c.chunk_strategy, count(e.embedding_id) AS embedding_count
               FROM chunks c JOIN documents d USING (document_id)
               LEFT JOIN chunk_embeddings e ON e.chunk_id = c.chunk_id
                 AND e.model_name = %s AND e.model_version = %s AND e.model_fingerprint = %s
               WHERE d.review_status = 'approved' AND c.strategy_version = %s
               GROUP BY c.chunk_strategy""", (MODEL_NAME, MODEL_VERSION, fingerprint, strategy_version)
        ).fetchall()
        embedded_counts = {row["chunk_strategy"]: row["embedding_count"] for row in embeddings}
        if any(embedded_counts.get(strategy, 0) != counts.get(strategy, 0)
               for strategy in ("fixed_size", "section_aware")):
            raise HTTPException(status_code=409, detail="Semantic evaluation needs current model-fingerprinted embeddings for every approved chunk. BM25-only evaluation remains available with method=bm25.")
    approved_documents = connection.execute(
        """SELECT document_id, document_sha256, reviewed_at FROM documents
           WHERE review_status = 'approved' ORDER BY document_id"""
    ).fetchall()
    chunk_versions = connection.execute(
        """SELECT c.chunk_strategy, c.strategy_version, count(*) AS chunk_count,
                  string_agg(c.chunk_id::text || ':' || md5(c.chunk_text), ',' ORDER BY c.chunk_id) AS chunk_digests
           FROM chunks c JOIN documents d USING (document_id)
           WHERE d.review_status = 'approved'
           GROUP BY c.chunk_strategy, c.strategy_version
           ORDER BY c.chunk_strategy, c.strategy_version"""
    ).fetchall()
    corpus_snapshot = {"approved_documents": [
                           {"document_id": row["document_id"], "document_sha256": row["document_sha256"],
                            "reviewed_at": row["reviewed_at"].isoformat() if row["reviewed_at"] else None}
                           for row in approved_documents],
                       "chunk_versions": [
                           {"chunk_strategy": row["chunk_strategy"],
                            "strategy_version": row["strategy_version"],
                            "chunk_count": row["chunk_count"],
                            "content_sha256": hashlib.sha256((row["chunk_digests"] or "").encode()).hexdigest()}
                           for row in chunk_versions]}
    matrix = []
    for method in methods:
        for strategy in ("fixed_size", "section_aware"):
            observations = []
            for item in questions:
                result = run_retrieval(connection, RetrievalRequest(
                    question=item.question, method=method, chunk_strategy=strategy,
                    strategy_version=strategy_version, top_k=top_k
                ))
                if result.get("index_status"):
                    raise HTTPException(status_code=409, detail="Semantic embeddings are missing. Approve documents and run python -m app.embed before evaluation.")
                rank = next((row["rank"] for row in result["results"]
                             if row["document_id"] in item.expected_document_ids
                             and (not item.expected_pages or
                                  (row["page_start"] is not None and any(
                                      row["page_start"] <= page <= (row["page_end"] or row["page_start"])
                                      for page in item.expected_pages)))), None)
                observations.append({"question": item, "hit": rank is not None,
                                     "rr": 1 / rank if rank else 0.0,
                                     "timings": result["timings"],
                                     "ids": [row["chunk_id"] for row in result["results"]]})
            n = len(observations)
            hits = sum(row["hit"] for row in observations)
            mrr = sum(row["rr"] for row in observations) / n
            timing_names = ("total_request_ms", "corpus_load_ms", "embedding_load_ms",
                            "index_build_ms", "query_embedding_ms", "model_load_ms", "search_ms")
            timing_means = {name: sum(row["timings"].get(name, 0.0) for row in observations) / n
                            for name in timing_names}
            with connection.transaction():
                run = connection.execute(
                    """INSERT INTO evaluation_runs
                       (manifest_version, retrieval_method, chunk_strategy, top_k,
                        question_count, hit_count, mean_latency_ms, mean_reciprocal_rank,
                        manifest_sha256, embedding_model_name, embedding_model_version, corpus_snapshot,
                        embedding_model_fingerprint, model_initialization_ms,
                        chunk_strategy_version, mean_corpus_load_ms, mean_embedding_load_ms,
                        mean_index_build_ms, mean_query_embedding_ms, mean_model_load_ms, mean_search_ms)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                       RETURNING run_id""",
                    (manifest["manifest_version"], method, strategy, top_k, n, hits,
                     timing_means["total_request_ms"], mrr,
                     manifest_sha256,
                     MODEL_NAME if method == "semantic" else None,
                     MODEL_VERSION if method == "semantic" else None,
                     psycopg.types.json.Jsonb(corpus_snapshot), fingerprint if method == "semantic" else None,
                     initialization_ms if method == "semantic" else 0.0, strategy_version,
                     timing_means["corpus_load_ms"], timing_means["embedding_load_ms"],
                     timing_means["index_build_ms"], timing_means["query_embedding_ms"],
                     timing_means["model_load_ms"], timing_means["search_ms"]),
                ).fetchone()
                for observation in observations:
                    item = observation["question"]
                    connection.execute(
                        """INSERT INTO evaluation_results
                           (run_id, question_id, question_type, hit, reciprocal_rank, latency_ms,
                            retrieved_chunk_ids, corpus_load_ms, embedding_load_ms, index_build_ms,
                            query_embedding_ms, model_load_ms, search_ms)
                           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                        (run["run_id"], item.question_id, item.question_type, observation["hit"],
                         observation["rr"], observation["timings"]["total_request_ms"], observation["ids"],
                         observation["timings"]["corpus_load_ms"], observation["timings"].get("embedding_load_ms", 0),
                         observation["timings"].get("index_build_ms", 0),
                         observation["timings"].get("query_embedding_ms", 0),
                         observation["timings"].get("model_load_ms", 0), observation["timings"]["search_ms"]),
                    )
            matrix.append({"run_id": run["run_id"], "method": method, "chunk_strategy": strategy,
                           "question_count": n, "hit_rate": hits / n, "mean_reciprocal_rank": mrr,
                           "mean_latency_ms": timing_means["total_request_ms"],
                           "timings": timing_means,
                           "by_question_type": [
                               {"question_type": question_type,
                                "question_count": len(group),
                                "hit_rate": sum(row["hit"] for row in group) / len(group),
                                "mean_reciprocal_rank": sum(row["rr"] for row in group) / len(group),
                                "mean_latency_ms": sum(row["timings"]["total_request_ms"] for row in group) / len(group)}
                               for question_type in sorted({row["question"].question_type for row in observations})
                               for group in [[row for row in observations if row["question"].question_type == question_type]]
                           ]})
    return {"manifest_version": manifest["manifest_version"], "manifest_sha256": manifest_sha256,
            "corpus": manifest.get("corpus"),
            "model_initialization_ms": initialization_ms, "results": matrix}


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
