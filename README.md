# SBC RAG Assistant

An authenticated demo for answering questions about health benefits from a provisional set of plan documents. The six received files are not verified as standardized SBCs or public-source documents. Correctness, citations, table fidelity, and abstention when evidence is insufficient are core requirements.

## Project documents

- [PRD.md](PRD.md) — product goals, requirements, and acceptance criteria.
- [PLAN.md](PLAN.md) — selected stack, implementation milestones, and status.
- [ARCHITECTURE.md](ARCHITECTURE.md) — system components, data flow, and design decisions.
- [AGENTS.md](AGENTS.md) — repository guidance for coding agents.

## Current status and corpus

This repository contains a React/Vite frontend, a FastAPI API, Neon migrations and admin document/benefit review workflows, a Render Blueprint, project documentation, and six received PDFs under [`data/source-documents/received/`](data/source-documents/received/). Those files are the provisional development corpus, not verified SBCs. Local PDF ingestion and row-preserving chunking are implemented. Retrieval, evidence-backed answer generation, and evaluation data remain pending; parser, candidate extraction, and admin upload/authentication tests are in `backend/tests/`.

The signed-in UI has a page-flow skeleton for Plans, Chat (home), Profile, and admin tools. Admins can upload/inspect/review documents and review candidate benefits; Playground and Evaluation remain placeholders. Chat has a transcript, composer, starter prompts, and a new-chat action. Displayed turns stay in memory and clear when starting a new chat, signing out, or reloading/closing the page. Each question is sent independently to the current API; prior turns are not included as answer context. Plans and Profile remain placeholders, and chat returns the safe insufficient-evidence response until approved evidence and retrieval are connected. Admin navigation uses the Firebase custom claim for visibility only; the API enforces authorization on admin operations.

The six PDFs in [`data/source-documents/received/`](data/source-documents/received/) are the provisional development corpus for parsing, retrieval, answer-flow, and evaluation. The metadata in [`metadata.json`](data/source-documents/received/metadata.json) identifies them as unverified; the set includes medical plan/benefit summaries and dental and vision summaries, and public source URLs are not established. Do not describe them as verified SBCs or treat processing/review approval as SBC qualification. Report results as provisional and scoped to these six files. Final qualification of exactly six public standardized medical SBCs with HMO/PPO/HDHP coverage remains TBD and is not a blocker to development.

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

Storage capacity has not been estimated. The current provisional corpus ranges from 20 KB to 180 KB and from 2 to 7 pages where page counts are available. Record PDF sizes and derived-data volume during ingestion, then compare measured use with the database plan's current limits before deployment. Neon also has a separate compute quota; check actual activity and current provider limits rather than assuming a particular workload will fit. Provider tiers and quotas can change.

## Local development

### Requirements

- Node.js 20 or newer and npm.
- Python 3.11 or newer.
- A Firebase project with Email/Password sign-in and account creation enabled, plus a registered web app.
- A Firebase service account for the API, stored outside this repository.
- A Neon Postgres database for applying the initial schema migration.

### Configure Firebase

1. Copy the root `.env.example` values into `frontend/.env.local` and fill in the Firebase web app values. Set `VITE_API_BASE_URL=http://localhost:8000`.
2. Copy the backend values from `.env.example` into a repository-root `.env`. Set `FIREBASE_PROJECT_ID`, `DATABASE_URL`, and `GOOGLE_APPLICATION_CREDENTIALS` to the Firebase project ID, Neon connection string (with SSL enabled), and path to the Firebase service-account JSON file. Keep that JSON file outside the repository.
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

To create the relational schema in Neon, run this after setting `DATABASE_URL`:

```bash
python -m app.db.migrate
```

The migrations create the plan, document, parsed-page/table, chunk, benefit-record, and ordinary embedding-value tables. Embeddings use PostgreSQL `DOUBLE PRECISION[]`; the migrations do not install or use pgvector. Migration `002_benefit_review.sql` adds an idempotency index for source-backed benefit candidates, and `003_document_ingestion.sql` adds page tables and ingestion/review details. Run `python -m app.db.migrate` after pulling schema changes. The API database layer supports admin document upload/review and benefit review; chat retrieval is not connected yet.

### Upload and ingest documents

An admin can upload a PDF from **Documents** in the app, along with plan metadata and an optional public source URL. Uploads are stored in Neon as unverified `candidate` documents with `uploaded` status. The default size limit is 15 MB; configure `MAX_UPLOAD_BYTES` on the API to change it. Uploading does not make a document queryable or establish that it is an SBC.

Install backend dependencies, apply migrations, then run the local ingestion command from `backend/` while `DATABASE_URL` is configured in the repository-root `.env`:

```bash
python -m app.ingest
```

The command downloads pending PDFs from Neon, parses page text and table cells with pdfplumber, writes page/table provenance, and creates both fixed-size and section-aware chunks. Table rows stay intact with their headers even when a row exceeds the target chunk size. Parse issues remain visible in the admin Documents page. After processing, inspect pages/chunks and approve or reject the document. Approval admits a document to the provisional development workflow; it does not establish SBC status or public availability. The local CLI needs database credentials and uses local CPU/memory; Render does not run parsing.

Backend parser, candidate extraction, and admin upload/authentication tests are in `backend/tests/`. Run them from `backend/` with `python -m pytest`.

To grant or revoke an admin claim for an existing Firebase account, use the local CLI with the service-account credentials configured above:

```bash
python -m app.admin_claims grant user@example.com
python -m app.admin_claims revoke user@example.com
```

Only run this trusted local command for designated admins. Users must refresh their Firebase ID token after a claim change.

### Run the frontend

In another terminal:

```bash
cd frontend
npm install
npm run dev
```

Open the URL Vite prints (normally `http://localhost:5173`) and register an account or sign in with an existing Firebase user. The chat endpoint currently returns an explicit insufficient-evidence response because the provisional corpus and retrieval implementation are not connected yet. The Debug details section shows response status, citations, and evidence-path information.

For a production frontend bundle, run `npm run build` from `frontend/`.

### Deploy the Phase 1 scaffold to Render

The root [`render.yaml`](render.yaml) defines the free API web service and static frontend. Connect the repository as a Render Blueprint and provide the prompted Firebase, Neon, and frontend environment values. The API and frontend public URLs are not known until Render creates the services; use temporary values for `FRONTEND_ORIGIN` and `VITE_API_BASE_URL` during initial creation, then replace them with the actual service URLs below. Upload the Firebase service-account JSON in the API service's **Secret Files** as `firebase-service-account.json`; the Blueprint points `GOOGLE_APPLICATION_CREDENTIALS` to `/etc/secrets/firebase-service-account.json`. Do not put this file or its contents in the repository.

After Render creates both services, set `VITE_API_BASE_URL` on the static site to the API service's public `https://…onrender.com` URL and redeploy the static site. Set `FRONTEND_ORIGIN` on the API service to the static site's public URL and redeploy the API. The frontend values are embedded at build time, so changing them requires a new static-site build. The API service may sleep when idle and have a delayed first response. Neon remains an external service; the Blueprint does not provision it. Confirm the current free-tier, account-verification, and no-card terms in your Render, Neon, and Firebase accounts before deployment.

## Planned capabilities

The admin **Benefits review** page can extract candidate benefit values from detected table rows (falling back to parsed page text), preserve source wording and page/section context, and let an admin review or correct each candidate and its dimensions. It requires an uploaded and locally ingested document. Candidate extraction never verifies a value automatically, and the current answer endpoint does not consume reviewed records yet.

- Use the six received PDFs as a provisional development/evaluation corpus, preserving document identity, actual type, coverage type, sections, pages, and provenance. Keep their SBC/public-source status unverified unless independently established.
- Resolve final qualification of exactly six public standardized medical SBCs spanning HMO/PPO/HDHP; run separate corpus-specific evaluation before making SBC performance claims.
- Compare fixed-size and section-aware, row-preserving chunking.
- Independently evaluate BM25 and semantic retrieval using 20–30 labeled questions.
- Extract deductible, ER cost-sharing, copay, and out-of-pocket maximum values into auditable structured records.
- Answer supported questions with citations; clarify ambiguous plan names and abstain when evidence is missing, conflicting, or unverified.
- Show a multi-turn ChatGPT-style conversation in the active session. Chat messages remain in browser memory only and clear on new chat, sign-out, reload, or page close; they are not saved to the backend or browser storage.
- Show basic answer diagnostics to all users and detailed retrieval, parsing, extraction, and ingestion diagnostics to admins.
- Measure retrieval and answer accuracy, extraction accuracy, and latency. Defer token-usage measurement until optional Gemini phrasing is enabled. Keep live chat text in frontend memory only and clear it at session end; store no ordinary live query text. Retain only the authored evaluation manifest and aggregate/per-run evaluation results needed to report metrics.

The initial implementation compares BM25 with one semantic retrieval method: sentence-transformer embeddings generated locally and searched by FAISS. Neon remains the cloud relational database for durable app records and uploads, and stores embedding values as ordinary records; it does not perform vector search. The deployed API loads approved embeddings into an in-memory FAISS index and rebuilds it after restarts or corpus approval changes. Chroma or pgvector would be alternative vector-search implementations, not additional retrieval methods, and are out of scope unless evaluation or a concrete deployment constraint justifies changing the design.

## Documentation expectations

As implementation proceeds, update this README with setup and run instructions, actual parser and chunking decisions, measured BM25 versus semantic results, extraction accuracy, limitations, and what additional budget would change. Clearly label measurements from the current six files as provisional and corpus-scoped; do not present them as results on verified SBCs.
