# SBC RAG Assistant

An authenticated demo for answering questions about health benefit plans from real Summary of Benefits and Coverage (SBC) documents. Correctness, citations, table fidelity, and abstention when evidence is insufficient are core requirements.

## Project documents

- [PRD.md](PRD.md) — product goals, requirements, and acceptance criteria.
- [PLAN.md](PLAN.md) — selected stack, implementation milestones, and status.
- [ARCHITECTURE.md](ARCHITECTURE.md) — system components, data flow, and design decisions.
- [AGENTS.md](AGENTS.md) — repository guidance for coding agents.

## Current status and corpus

This repository contains a minimal React/Vite frontend and FastAPI API scaffold, project documentation, and six received candidate PDFs under [`data/source-documents/received/`](data/source-documents/received/). Ingestion, database persistence, retrieval, evidence-backed answer generation, evaluation data, and tests have not yet been added.

The received PDFs appear to be plan or benefit summaries, including dental and vision summaries, rather than qualifying standardized medical SBC forms. They do not yet meet the requirement for exactly six public SBCs. No HDHP SBC has been identified. We will make practical use of the supplied PDFs for exploratory parser, table, chunking, extraction, and pipeline development, while labeling their outputs as candidate-derived. This work does not qualify them for the active corpus or final corpus evaluation. Selecting the qualifying corpus is required for final acceptance and representative evaluation, but does not block building the skeleton and pipeline. See [ARCHITECTURE.md](ARCHITECTURE.md) for inventory and qualification notes. Do not count a candidate toward the corpus until its document type, plan identity, and public source are verified.

## Selected technology direction

- Python 3.11, FastAPI, React, TypeScript, and shadcn/ui.
- Firebase Authentication for sign-in and admin roles; the FastAPI server will verify tokens and enforce permissions.
- Neon Postgres for durable document metadata, uploaded PDF bytes, parsed content, extracted benefit records, citations, and evaluation records.
- pdfplumber for initial PDF extraction, with Camelot added selectively if inspection shows a table needs it.
- BM25 plus FAISS semantic search. The local ingestion CLI generates document embeddings; the API generates query embeddings with the same sentence-transformer model and searches an in-memory FAISS index. Store approved embedding values and model/chunk IDs in Neon so the API can build or refresh its index after restarts and approvals. No embedding API or pgvector index is needed initially. Verify the deployed API's model/index memory and startup requirements.
- Evaluate four combinations: BM25 or semantic vector retrieval, each over fixed-size or semantic/section-aware table-safe chunks. The admin-only evaluation playground will let admins compare configurations; ordinary answer mode uses the measured default.
- Initial answers use deterministic formatting for verified facts, comparisons, citations, clarification, and abstention; Gemini is not part of the initial implementation. It may be added later as an optional final phrasing step over validated evidence and cannot supply facts or override abstention.
- Render Free for the React static site and FastAPI web service. The service may sleep when idle, so the first request can be delayed. Persist application data in Neon, not Render's ephemeral filesystem.

These selections target a free, no-credit-card demo within provider limits. Free tiers can sleep, pause, change limits, or require account verification; always confirm current terms before deployment. Admin PDF upload will be real. To fit free-host resource limits, the initial design stores uploads in Neon and uses a local authenticated/administrative ingestion command to parse, extract, embed, and write reviewed results back to Neon. Uploaded documents remain pending until extraction and provenance have been reviewed.

Storage capacity has not been estimated because the qualifying SBC files, their page counts, and actual PDF sizes are not yet known. The supplied candidates range from 20 KB to 180 KB and from 2 to 7 pages where page counts are available, but they are not the verified corpus and may not predict its storage needs. Record the selected PDFs' sizes and derived-data volume during ingestion, then compare measured use with the database plan's current limits before deployment. Neon also has a separate compute quota; check actual activity and current provider limits rather than assuming a particular workload will fit. Provider tiers and quotas can change.

## Local development

### Requirements

- Node.js 20 or newer and npm.
- Python 3.11 or newer.
- A Firebase project with Email/Password sign-in and account creation enabled, plus a registered web app.
- A Firebase service account for the API, stored outside this repository.

### Configure Firebase

1. Copy the root `.env.example` values into `frontend/.env.local` and fill in the Firebase web app values. Set `VITE_API_BASE_URL=http://localhost:8000`.
2. Copy the backend values from `.env.example` into a repository-root `.env`. Set `FIREBASE_PROJECT_ID` and `GOOGLE_APPLICATION_CREDENTIALS` to the Firebase project ID and path to the service-account JSON file. Keep that JSON file outside the repository.
3. In Firebase Console, enable the Email/Password provider. Users can register from the app; add `localhost` to Authorized domains if it is not already listed.
4. Set `FRONTEND_ORIGIN=http://localhost:5173` in the root `.env`.

### Run the API

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

The API health check is at `http://localhost:8000/api/health`; interactive API docs are at `http://localhost:8000/docs`.

### Run the frontend

In another terminal:

```bash
cd frontend
npm install
npm run dev
```

Open the URL Vite prints (normally `http://localhost:5173`) and sign in with the Firebase demo user. The chat endpoint currently returns an explicit insufficient-evidence response because no verified corpus, ingestion pipeline, or retrieval implementation is connected yet. The Debug details section shows response status, citations, and evidence-path information.

For a production frontend bundle, run `npm run build` from `frontend/`. The current API scaffold is local-development oriented; deployment configuration and database integration remain future work.

## Planned capabilities

- Ingest exactly six verified public SBCs with table rows, document identity, plan metadata, sections, pages, and source provenance preserved.
- Compare fixed-size and section-aware, row-preserving chunking.
- Independently evaluate BM25 and semantic retrieval using 20–30 labeled questions.
- Extract deductible, ER cost-sharing, copay, and out-of-pocket maximum values into auditable structured records.
- Answer supported questions with citations; clarify ambiguous plan names and abstain when evidence is missing, conflicting, or unverified.
- Show basic answer diagnostics to all users and detailed retrieval, parsing, extraction, and ingestion diagnostics to admins.
- Measure retrieval and answer accuracy, extraction accuracy, and latency. Defer token-usage measurement until optional Gemini phrasing is enabled. Do not retain ordinary user query text by default; keep only the authored evaluation manifest and aggregate/per-run evaluation results needed to report metrics.

The initial implementation compares BM25 with one semantic retrieval method: sentence-transformer embeddings generated locally and searched by FAISS. Neon remains the cloud relational database for durable app records and uploads, and stores embedding values as ordinary records; it does not perform vector search. The deployed API loads approved embeddings into an in-memory FAISS index and rebuilds it after restarts or corpus approval changes. Chroma or pgvector would be alternative vector-search implementations, not additional retrieval methods, and are out of scope unless evaluation or a concrete deployment constraint justifies changing the design.

## Documentation expectations

As implementation proceeds, update this README with setup and run instructions, actual parser and chunking decisions, measured BM25 versus semantic results, extraction accuracy, limitations, and what additional budget would change. Do not report evaluation results until they have been measured against verified SBCs.
