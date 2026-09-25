# SBC RAG Assistant

An authenticated demo for answering questions about health benefits from a provisional set of plan documents. The six received files are not verified as standardized SBCs or public-source documents. Correctness, citations, table fidelity, and abstention when evidence is insufficient are core requirements.

## Project documents

- [PRD.md](PRD.md) — product goals, requirements, and acceptance criteria.
- [PLAN.md](PLAN.md) — selected stack, implementation milestones, and status.
- [ARCHITECTURE.md](ARCHITECTURE.md) — system components, data flow, and design decisions.
- [AGENTS.md](AGENTS.md) — repository guidance for coding agents.

## Current status and corpus

This repository contains a React/Vite frontend, a FastAPI API, Neon migrations and admin document/benefit review workflows, a Render Blueprint, project documentation, and six received PDFs under [`data/source-documents/received/`](data/source-documents/received/). Those files are the provisional development corpus, not verified SBCs. Automatic PDF ingestion, row-preserving chunking, BM25 and FAISS retrieval, local embedding generation, admin retrieval/evaluation tools, and a deterministic cited answer path are implemented. The 25-question evaluation manifest and results remain provisional until the full corpus is reviewed and measured.

The signed-in UI has pages for Plans, Chat, Profile, and admin tools. Open Profile from the icon in the top-right account area; the Profile page includes a Sign out button. For admins, Plans combines the ready plan list with document upload, processing status, and inspection controls; members see only the plan list. Admins can optionally correct or verify candidate benefits, search queryable evidence in the Retrieval playground, inspect answer evidence health, and run four-way comparisons from Evaluation after labels are added. Chat has a transcript, composer, starter prompts, and a new-chat action. Displayed turns stay in memory and clear when starting a new chat, signing out, or reloading/closing the page. Follow-up requests send the previous question and resolved plan IDs from browser memory; the API stores no ordinary chat text. Plans lists queryable provisional documents. Admin navigation uses the Firebase custom claim for visibility only; the API enforces authorization on admin operations.

The six PDFs in [`data/source-documents/received/`](data/source-documents/received/) are the provisional development corpus for parsing, retrieval, answer-flow, and evaluation. The metadata in [`metadata.json`](data/source-documents/received/metadata.json) identifies them as unverified; the set includes medical plan/benefit summaries and dental and vision summaries, and public source URLs are not established. Do not describe them as verified SBCs or treat processing/review approval as SBC qualification. Report results as provisional and scoped to these six files. Final qualification of exactly six public standardized medical SBCs with HMO/PPO/HDHP coverage remains TBD and is not a blocker to development.

## Selected technology direction

- Python 3.11, FastAPI, React, TypeScript, and shadcn/ui.
- Firebase Authentication for sign-in and admin roles; the FastAPI server will verify tokens and enforce permissions.
- Neon Postgres for durable document metadata, uploaded PDF bytes, parsed content, extracted benefit records, citations, and evaluation records.
- pdfplumber for initial PDF extraction, with Camelot added selectively if inspection shows a table needs it.
- BM25 plus FAISS semantic search. FastAPI automatically parses, extracts, embeds, and assesses uploaded documents; `python -m app.pipeline` remains available for local maintenance. The API generates query embeddings with the same sentence-transformer model and builds a FAISS index from queryable vectors for semantic searches. Vectors are ordinary Neon array values; no embedding API or pgvector index is used. The admin playground compares configurations; ordinary answer mode will use the measured default after evaluation.
- Evaluate four combinations: BM25 or semantic vector retrieval, each over fixed-size or semantic/section-aware table-safe chunks. The admin-only evaluation playground lets admins compare configurations. Ordinary chat currently uses BM25 with section-aware chunks as an explicitly provisional default; select the measured default after labeling and running the evaluation set.
- Initial answers use deterministic formatting for supported facts, comparisons, citations, clarification, and abstention; Gemini is not part of the initial implementation. It may be added later as an optional final phrasing step over validated evidence and cannot supply facts or override abstention.
- Render Free for the React static site and FastAPI web service. The service may sleep when idle, so the first request can be delayed. Persist application data in Neon, not Render's ephemeral filesystem.

These selections target a free, no-credit-card demo within provider limits. Free tiers can sleep, pause, change limits, or require account verification; always confirm current terms before deployment. Admin PDF uploads are stored in Neon and automatically processed by the FastAPI service. Successful admin uploads are automatically approved and available for questions after all required stages complete with usable retrieval evidence. Render Free memory fit remains unverified; local profiling exceeded its current 512 MiB limit.

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

The migrations create the plan, document, parsed-page/table, chunk, benefit-record, ordinary embedding-value, and evaluation result tables. Embeddings use PostgreSQL `DOUBLE PRECISION[]`; migrations do not install or use pgvector. Migrations `004` and `005` store evaluation metrics and provenance snapshots, per-question timing breakdowns, and model fingerprints, without question text. Migration `006` records reviewer confirmation of benefit source sections. Migration `007` adds readiness states, stage statuses, and warnings. Migration `008` adds an automatic ingestion queue marker and attempt count. Run `python -m app.db.migrate` after pulling schema changes; Render also runs migrations before starting the API. Admin retrieval endpoints remain separate from ordinary chat.

### Upload and process documents

An admin can upload a PDF from the **Source documents** section of **Plans** in the app, along with plan metadata and an optional public source URL. The **Upload document** button at the top of Plans jumps to that section. Uploads are stored in Neon with `uploaded` status. The default size limit is 15 MB; configure `MAX_UPLOAD_BYTES` on the API to change it. FastAPI starts processing after returning the upload response. The section refreshes processing status until the document is `approved` or `failed`. Successful admin uploads are automatically approved for questions; no document verification click is needed. Processing must finish before Chat can use the document. The separate `candidate` corpus status records that SBC eligibility and public availability remain unverified by this application.

For maintenance or to process documents uploaded before automatic ingestion was enabled, run the local pipeline from `backend/` while `DATABASE_URL` is configured in the repository-root `.env`:

```bash
python -m app.pipeline
```

The automatic task and maintenance command use the same pipeline: download PDF bytes from Neon; parse page text and table cells with pdfplumber; create fixed-size and section-aware chunks with page, row, and section provenance; extract benefit candidates; generate local sentence-transformer embeddings; and check readiness. Table rows stay intact with their headers. The admin Plans page shows `parsing`, `chunking`, `benefit_extraction`, and `embedding` stages and any warnings or critical error. An admin upload becomes `approved` only after all stages complete and both chunk sets have usable current embeddings. Documents without an admin uploader retain `ready` or `ready_with_warnings` when processing succeeds. Processing, incomplete, rejected, and failed documents remain unavailable. Admins may inspect or delete a document; automatic approval does not establish SBC status or public availability.

An isolated page parse failure, ambiguous benefit, table extraction failure, or candidate with no detected section is a warning when usable evidence remains. Unreadable PDFs, essentially no usable text, missing plan identity, a processing crash, or insufficient embeddings are critical. A warning limits only affected questions; supported values elsewhere can still be answered.
Queued jobs survive a process restart. The API resumes them on startup or when an admin opens Plans. It stops after two interrupted attempts and shows a failure; use **Retry** to start again. The trash icon on each document permanently deletes it after confirmation, along with its pages, chunks, embeddings, benefit records, and any plan no other document uses; documents still queued or processing cannot be deleted. The maintenance command prints each document's stage result and exits with a nonzero status if any document fails; inspect the admin Plans page for persisted details.

For maintenance, the individual parsing/chunking and embedding commands remain available:

```bash
python -m app.ingest
python -m app.embed
```

The parser retains all extracted table rows, including rows before and at a detected header. It retains original cells in `raw_rows` when a duplicated helper-cell value is removed from the normalized row. To refresh a document and replace its derived evidence, run `python -m app.pipeline --reprocess-id DOCUMENT_ID` locally. This re-runs all stages and reassesses readiness; previous parsed pages, chunks, embeddings, and benefit records are replaced. `python -m app.ingest --reprocess-id DOCUMENT_ID` reparses only and leaves the document unavailable pending the full pipeline.

A page with multiple detected headings has no single page-level section label. Row-level section provenance is kept where detected; a numerical candidate lacking a usable detected section cannot support an answer until an admin corrects it.
The parser recognizes the title-case benefit headings used in the Kaiser Traditional Plan summary, carries those headings to table rows and nearby text, and stores text wording separately from its line number in chunk provenance. For that document, `None` is retained as the stated deductible value; it is not changed to `$0` or used as a numeric amount for ordering comparisons. Plan and drug deductible rows are kept distinct when answering. Reprocess previously uploaded copies after updating the backend so stored chunks and benefit records include the corrected provenance.

The first run downloads the configured sentence-transformer model if it is not cached. Parsing and embedding use CPU and memory on whichever machine runs the API or maintenance command. Set `EMBEDDING_BATCH_SIZE` to control peak embedding memory; the local default is 32, and the Render Blueprint sets it to 1 with single-threaded CPU libraries. A full local API upload of a small vision PDF peaked at about 555 MiB with batch size 1; a larger candidate PDF benchmark reached about 576 MiB. Render Free currently provides 512 MiB, so automatic processing on that plan remains unverified and may fail until the deployed runtime is measured. The original PDF and queued state remain durable in Neon if the API restarts.

### Retrieval playground and evaluation

In **Playground**, select BM25 or Semantic (FAISS), choose a chunk strategy, inspect ranked chunks and provenance, or preview the deterministic answer with that configuration. Plan, document, and section filters apply to evidence search; answer preview resolves plans from the question and uses supported structured records for numerical answers. Semantic search requires queryable chunks to have current embeddings; model name/version and a fingerprint of loaded model weights are checked, and vector dimensions, numeric finiteness, and nonzero norms are validated before indexing. Reprocess documents locally if the model fingerprint changes. Model configuration defaults to `EMBEDDING_MODEL=sentence-transformers/all-MiniLM-L6-v2` and `EMBEDDING_MODEL_VERSION=all-MiniLM-L6-v2`; keep these consistent between embedding and API processes.

The manifest contains 25 manually checked questions for the six received candidate PDFs. Each entry has a unique `question_id`, `question`, `question_type`, `expected_answer`, source PDF SHA-256 labels, and `expected_pages`. SHA-256 labels map the questions to the exact source PDFs and are resolved to current Neon document IDs at run time, so the labels do not depend on database insertion order. Cross-plan questions can require retrieval of every labeled document; their reciprocal rank is based on the last required source retrieved. The PDFs and answer key are provisional; their SBC status and public availability remain unverified. Check parser output and source locations before relying on results. The runner scores expected document/page evidence in top-k, reciprocal rank, and latency. In the admin **Evaluation** page, choose BM25-only, semantic-only, or all four BM25/semantic × fixed-size/section-aware configurations. BM25 runs do not require embeddings; semantic runs require current, complete embeddings. Timings separately report chunk loading, embedding loading, index construction, query embedding/model initialization, and search. Evaluation model initialization is reported separately from per-query measurements. Stored runs include model identity/fingerprint, approved-document and chunk-version snapshots, and per-question metrics/retrieved chunk IDs, but no question or expected-answer text. Label any measurements as provisional and corpus-scoped.

Backend parser, candidate extraction, and admin upload/authentication tests are in `backend/tests/`. Run them from `backend/` with `python -m pytest`.

### Answer flow

`POST /api/chat` requires a Firebase ID token. The request accepts `question`, optional `context_plan_ids`, and optional `previous_question` for short follow-ups. The browser sends only the latest in-memory context; the server keeps no transcript. Responses include `answered`, `clarification_needed`, or `insufficient_evidence`, matched plan names, citations with plan/section/page/document when available, and basic diagnostics. Admins receive evidence IDs and retrieval ranks in the response diagnostics. `GET /api/plans` lists plans with ready, ready-with-warnings, or previously approved provisional documents; `POST /api/admin/answer/preview` accepts the chat fields plus `method` and `chunk_strategy`; `GET /api/admin/answer-health` reports document, parse, benefit, chunk, and embedding counts to admins. Admin document list and inspection endpoints include stage status, warnings, and critical error details.

Numerical deductible, emergency room cost-sharing, copay, and out-of-pocket questions use unambiguous structured candidates or explicitly verified benefits from queryable documents. A usable record needs one stated value, matching requested context, and a source page and section. Ambiguous, conflicting, missing, or untraceable evidence for the requested context causes clarification or abstention. An isolated warning in another part of the document does not suppress a supported answer. Broader coverage questions quote a matching source row with traceable section and page; multiple differing rows require clarification. Processing readiness does not qualify a document as an SBC or establish a public source.

Automatically detected sections can support numerical answers when usable. Admins can optionally correct or explicitly confirm them during benefit review. Ambiguous candidates in the requested context block numerical answers. Lower/higher comparisons identify a plan only when values have comparable units; comparisons across medical, dental, and vision coverage types require clarification. Retrieval excludes documents marked ineligible.

`ANSWER_RETRIEVAL_METHOD` defaults to `bm25` and `ANSWER_CHUNK_STRATEGY` to `section_aware` for broader chat questions. These are provisional settings, not measured winners. Set both on the API service after the labeled comparison identifies a default. Semantic chat retrieval also requires current local embeddings. The current retrieval implementation loads approved evidence and builds the search index during each request; startup caching and deployment memory checks remain open.

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

Open the URL Vite prints (normally `http://localhost:5173`) and register an account or sign in with an existing Firebase user. Chat answers supported questions after automatic processing marks documents ready and their evidence is usable. Otherwise it asks for clarification or reports insufficient evidence. The answer details show matched plans, citations, and the evidence path; admins see ranked retrieval traces and evidence-gate details.

For a production frontend bundle, run `npm run build` from `frontend/`.

### Deploy the Phase 1 scaffold to Render

The root [`render.yaml`](render.yaml) defines the free API web service and static frontend. Connect the repository as a Render Blueprint and provide the prompted Firebase, Neon, and frontend environment values. The API and frontend public URLs are not known until Render creates the services; use temporary values for `FRONTEND_ORIGIN` and `VITE_API_BASE_URL` during initial creation, then replace them with the actual service URLs below. Upload the Firebase service-account JSON in the API service's **Secret Files** as `firebase-service-account.json`; the Blueprint points `GOOGLE_APPLICATION_CREDENTIALS` to `/etc/secrets/firebase-service-account.json`. Do not put this file or its contents in the repository.

After Render creates both services, set `VITE_API_BASE_URL` on the static site to the API service's public `https://…onrender.com` URL and redeploy the static site. Set `FRONTEND_ORIGIN` on the API service to the static site's public URL and redeploy the API. The frontend values are embedded at build time, so changing them requires a new static-site build. The API service may sleep when idle and have a delayed first response. Neon remains an external service; the Blueprint does not provision it. Confirm the current free-tier, account-verification, and no-card terms in your Render, Neon, and Firebase accounts before deployment.

## Capabilities and remaining work

The admin **Benefits review** page shows candidate benefit values from table cells and nearby continuation rows, falling back to parsed page text when tables are unavailable. It shows detected sections and carries network, individual/family, and period context. Candidates can support cited numerical answers automatically when unambiguous. Admins can correct and explicitly verify candidates as needed. To refresh parsed tables after a parser change, reprocess the document with `python -m app.pipeline --reprocess-id DOCUMENT_ID`; reprocessing replaces old chunks, embeddings, parsed pages, and benefit records. Extraction accuracy is still pending manual measurement across the provisional corpus.

- Use the six received PDFs as a provisional development/evaluation corpus, preserving document identity, actual type, coverage type, sections, pages, and provenance. Keep their SBC/public-source status unverified unless independently established.
- Resolve final qualification of exactly six public standardized medical SBCs spanning HMO/PPO/HDHP; run separate corpus-specific evaluation before making SBC performance claims.
- Compare fixed-size and section-aware, row-preserving chunking.
- Independently evaluate BM25 and semantic retrieval using 20–30 labeled questions.
- Extract deductible, ER cost-sharing, copay, and out-of-pocket maximum values into auditable structured records.
- Answer supported questions with citations; clarify ambiguous plan names and abstain when requested evidence is missing, ambiguous, conflicting, or untraceable.
- Show a multi-turn ChatGPT-style conversation in the active session. Chat messages remain in browser memory only and clear on new chat, sign-out, reload, or page close; they are not saved to the backend or browser storage.
- Show basic answer diagnostics to all users and detailed retrieval, parsing, extraction, and ingestion diagnostics to admins.
- Measure retrieval and answer accuracy, extraction accuracy, and latency. Defer token-usage measurement until optional Gemini phrasing is enabled. Keep live chat text in frontend memory only and clear it at session end; store no ordinary live query text. Retain only the authored evaluation manifest and aggregate/per-run evaluation results needed to report metrics.

The initial implementation compares BM25 with one semantic retrieval method: sentence-transformer embeddings generated locally and searched by FAISS. Neon remains the cloud relational database for durable app records and uploads, and stores embedding values as ordinary records; it does not perform vector search. The API currently loads queryable embeddings and builds an in-memory FAISS index for each semantic request, so readiness changes are reflected on the next search. Chroma or pgvector would be alternative vector-search implementations, not additional retrieval methods, and are out of scope unless evaluation or a concrete deployment constraint justifies changing the design.

## Documentation expectations

As implementation proceeds, update this README with setup and run instructions, actual parser and chunking decisions, measured BM25 versus semantic results, extraction accuracy, limitations, and what additional budget would change. Clearly label measurements from the current six files as provisional and corpus-scoped; do not present them as results on verified SBCs.
