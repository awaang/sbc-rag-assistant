# Implementation Plan: SBC RAG Demo

This plan records the agreed technology direction and tracks implementation. Phase 1's local frontend/API scaffold, Firebase auth foundation, initial Neon schema migration, and Render Blueprint are implemented. Ingestion, runtime database access, retrieval, and evidence-backed answering remain pending.

## Selected stack

- **Runtime/API:** Python 3.11 and FastAPI for ingestion commands, retrieval, answer logic, and the authenticated HTTP API.
- **Frontend:** React + TypeScript with shadcn/ui; serve as a Render static site and call the FastAPI API.
- **Authentication/roles:** Firebase Authentication on the no-cost Spark plan for email/password or social login. FastAPI verifies ID tokens for every protected request. A local one-time admin bootstrap command assigns Firebase custom claims; no public self-promotion endpoint.
- **Persistent data:** Neon Postgres Free for plan/document metadata, uploaded PDF bytes, parsed pages/rows/chunks, verified structured benefit records, provenance, ingestion state, and evaluation results. Use ordinary SQL access through a repository/data-access layer; do not expose Neon credentials to the browser.
- **Semantic retrieval:** Generate document embeddings with `sentence-transformers/all-MiniLM-L6-v2` in the local ingestion CLI and query embeddings in the FastAPI process, using the same configurable model version. Persist approved document embedding values as ordinary per-chunk data in Neon; Neon does not perform vector search and pgvector is not used. The API builds an in-memory FAISS index from approved embeddings at startup and refreshes it after approval changes. No embedding API or shared filesystem is required. Verify that the selected Render service can load the model and index within its memory/startup limits.
- **Keyword retrieval:** `rank-bm25` over the same canonical chunks, independently measurable from semantic search.
- **PDF handling:** `pdfplumber` first; evaluate actual SBC output and add Camelot only for tables where it demonstrably improves row/cell structure.
- **Answers, initial phase:** Deterministic formatting for structured numeric lookups and comparisons, citations, clarification, and abstention. Do not integrate Gemini in the initial implementation.
- **Answers, later phase:** Gemini may be added as an optional final phrasing adapter only after the deterministic answer path is implemented and evaluated. It receives validated facts/evidence and cannot choose values, create citations, fill missing evidence, or override abstention. Do not make initial completion dependent on Gemini or a free tier.
- **Deployment:** Render Free static site + web service; Neon and Firebase are external managed services. Expect API sleep/cold starts and ephemeral Render filesystems. Store durable state in Neon. Do not require a custom domain or paid persistent disk.
- **Uploaded source files:** Store modest PDFs as PostgreSQL binary data in Neon for the initial six-plan demo to avoid another account/service and keep uploads durable. Impose a documented upload-size limit below provider/request limits. If corpus size outgrows database storage, revisit object storage only after verifying a no-card option.
- **Ingestion execution:** Admin upload through the deployed UI is real and durable, but expensive parsing/embedding runs through an admin ingestion CLI on the developer machine. The CLI reads pending PDFs and metadata from Neon, processes them locally, writes parsed/provenance/extraction/embedding records back to Neon, and marks them `needs_review`. Admin approval is required before documents enter normal retrieval. No uploaded file or generated index depends on Render's ephemeral filesystem.
- **Evaluation/tests:** pytest for backend/parser/retrieval/auth/citation/evidence behavior; frontend checks as appropriate. Store a versioned 20–30 question evaluation manifest with verified expected values and source locations. Record accuracy, latency, retrieval results by method/question type, and extraction accuracy. Defer token usage measurement until optional Gemini synthesis is enabled.
- **Secrets:** Environment variables for Neon connection string, Firebase project/service credentials, and deployment configuration. Privileged Firebase credentials exist only in local admin tooling or protected server secrets; never in React or source control.

## Retrieval and chunking experiment

- The two retrieval methods are **BM25 keyword retrieval** (`rank-bm25`) and **semantic vector retrieval** (local sentence-transformer embeddings searched with local FAISS). These methods differ in how they find relevant chunks; neither replaces the other in the baseline evaluation.
- The two chunking strategies are **fixed-size chunking** and **semantic/section-aware chunking**. Both must preserve table rows and the headers/context needed to interpret them.
- Evaluate the four combinations (BM25 + fixed-size, BM25 + semantic/section-aware, vector + fixed-size, vector + semantic/section-aware) against the same labeled questions and report retrieval/answer results by question type.
- Add an **admin-only evaluation playground** that lets an admin select a retrieval method and chunking strategy, then submit a question and inspect answer status, citations, and diagnostics. This is an evaluation control, not an unreviewed production routing knob: ordinary user mode uses the measured default configuration; admins can compare configurations and inspect detailed scores/run traces.
- Store versioned chunks for both strategies and associate each retrieval run with its chunking strategy, retrieval method, model/version, and top-k/configuration so results are reproducible. Do not duplicate original PDFs or verified benefit records for each strategy.
- Numerical questions continue to use verified structured benefit records for their value source; selected retrieval/chunking settings affect source-evidence retrieval and diagnostics, not the authority for numeric values.

## Ordered implementation phases

### Phase 1 — Corpus and runnable project skeleton

- **Completed project setup:** Six candidate PDFs have been received and provisionally classified in `ARCHITECTURE.md`; they remain separate from the qualifying corpus.
- **Scaffold added:** React + TypeScript + Vite frontend with shadcn-style UI primitives, Firebase email/password registration/sign-in, a chat form with collapsible diagnostics, and a FastAPI health/chat API. The protected chat endpoint currently abstains because there is no verified corpus or retrieval pipeline yet.
- [x] Establish a small Python backend and React TypeScript frontend layout; ingestion/evaluation/test directories will be added with those phases.
- [x] Add dependency/configuration files, local development instructions, `.env.example` containing names only, and ignores for secrets/build outputs.
- [x] Add Firebase registration/sign-in and FastAPI ID-token verification; Neon relational schema/migration with ordinary embedding values and no pgvector; FastAPI health/API skeleton; local admin-claim bootstrap command; and Render Blueprint without embedded secrets. Protect each authenticated/admin route when it is introduced.
- [x] Document local run and Render deployment setup, including manual provider configuration, cold starts, and free-tier limits.

**Milestone:** Phase 1 implementation is complete. Local commands and deployment configuration are documented. A real deployment still requires Firebase/Neon/Render accounts, credentials, and the manual environment settings in README; external resources have not been provisioned from this repo.

### Corpus prerequisite — select the verified six-document set

- [ ] Select exactly six verified public SBC PDFs; record source URLs, insurer, plan identity/type/year, and confirm the desired HMO, PPO, and HDHP mix where feasible. Current candidates appear not to qualify and contain no identified HDHP SBC.
- [ ] Keep this corpus requirement visible, and make practical use of the supplied candidates for exploratory parsing, table handling, chunking, extraction, and pipeline development with clear candidate labels. Candidate work does not qualify files for the active corpus or final corpus evaluation. Complete corpus selection before final corpus ingestion and end-to-end evaluation.

**Milestone:** Six eligible, public SBCs are documented as the active corpus. This is required for final acceptance and representative evaluation, but does not block the project skeleton.

### Phase 2 — SBC parsing, provenance, and table-safe chunks

- [ ] Build source-document registry and real admin PDF upload, storing original PDFs and upload status in Neon.
- [ ] Implement the local ingestion CLI: fetch pending uploads, parse pages/tables, preserve section/page and table headers, and report parse issues.
- [ ] Keep documents and extracted records in pending/review states until an admin approves them; ensure upload alone never makes a document queryable.
- [ ] Compare fixed-size chunking with semantic/section-aware chunking while never splitting a table row from its interpretive headers/context.
- [ ] Review parser output on the supplied candidates and fixtures during pipeline development, then on all six verified SBCs once selected; add Camelot only where it improves real table fidelity. Candidate parsing is exploratory and does not qualify a candidate for the corpus.
- [ ] Add parser/chunker fixtures covering provenance, intact rows, missing sections, and malformed/unreadable pages.

**Milestone:** Available PDFs produce inspectable pages, table rows, and chunks with traceable provenance. Repeat/complete this review for the six verified SBCs after corpus selection.

### Phase 3 — Structured benefit extraction and admin review

- [ ] Define typed records for deductible, ER cost sharing, copays, and out-of-pocket maximum, preserving exact SBC wording and distinctions (network, individual/family, deductible/coinsurance).
- [ ] Extract candidate values with source page/section/table-row references and explicit statuses (`pending_review`, `verified`, `missing`, `ambiguous`, `conflicting`).
- [ ] Provide admin review/edit/approval UI; only verified values and approved document chunks are queryable.
- [ ] Measure extraction accuracy against manually verified labeled values by category and plan.

**Milestone:** Numerical answers use reviewed, provenance-backed data; uncertain values stay unavailable.

### Phase 4 — BM25 and semantic retrieval baselines

- [ ] Generate sentence-transformer embeddings locally for approved chunks and persist them with chunk IDs/model version in Neon; build the FAISS search index in the API process from approved embeddings and refresh it after approval or ingestion changes.
- [ ] Add plan/document/section filtering without losing provenance.
- [ ] Create 20–30 evaluation questions with verified expected evidence locations, answer labels, and question types from the selected corpus.
- [ ] Measure the four retrieval/chunking combinations independently (e.g. supporting evidence in top-k) on identical evaluation questions and compare by question type.
- [ ] Add an admin-only evaluation playground for selecting BM25 or semantic search and fixed-size or semantic/section-aware chunks; show answer/citation diagnostics and detailed result traces to admins.
- [ ] Record latency and retrieval scores; select runtime retrieval behavior from measured results, retaining both methods for comparison.

**Milestone:** Reproducible retrieval results explain where BM25 and semantic search help or fail.

### Phase 5 — Authenticated answer flow and diagnostics

- [ ] Confirm Firebase token verification on every protected FastAPI request and admin custom claims on every upload/review/ingestion-management endpoint; these checks are implemented alongside the endpoints and covered here with authorization review.
- [ ] Resolve plans and ask for clarification for ambiguous names.
- [ ] Route numerical lookups and comparisons through verified structured records; use retrieval evidence for broader coverage questions.
- [ ] Apply provenance/evidence gate, conflict checks, citation validation, and explicit abstention before any synthesis.
- [ ] Implement and evaluate the complete deterministic, cited answer path without Gemini, including structured lookups, comparisons, clarification, and abstention.
- [ ] Show basic diagnostics to all users (matched plans, evidence citations, answer/abstention status); show admins detailed retrieval ranks, extraction/parser status, and ingestion/index health.
- [ ] Use measured results to select ordinary-user defaults; retain explicit configuration selection in the evaluation playground.
- [ ] Add tests for authentication, admin authorization, comparisons, citations, ambiguity, missing/conflicting evidence, and uploaded-document approval state.

**Milestone:** Authenticated users receive supported cited answers or clear clarification/abstention, with role-appropriate diagnostics.

### Phase 6 — Deployment, evaluation, and documentation

- [ ] Deploy React static site and FastAPI web service on Render Free; configure Firebase authorized domains and server secrets; connect Neon Free.
- [ ] Ensure the review UI communicates backend cold start and retries safely; verify upload-to-local-ingestion-to-review-to-answer lifecycle.
- [ ] Run the labeled set against the selected verified corpus; report answer/extraction accuracy, per-method retrieval results by question type, and latency. Defer token usage reporting until optional Gemini phrasing is enabled.
- [ ] Document actual chunking/parser/vector choices and observed limits, free-tier behavior, results, and what additional budget would change.

**Milestone:** The deployed demo is reproducible within no-card free-tier constraints and reports measured evidence quality.

### Later optional phase — Gemini phrasing

- [ ] Only after the initial answer flow is complete, deployed, and evaluated, optionally add Gemini behind an adapter to phrase validated answer content.
- [ ] Verify the Gemini path preserves backend-selected facts, citations, and abstention, and compare quality/latency/token use with deterministic output.
- [ ] Keep the application fully functional with Gemini disabled or unconfigured.

## Definition of done

- Exactly six verified public SBCs spanning HMO, PPO, and HDHP are in the active corpus.
- Admin uploads are durable; ingestion is real, locally executed, reviewable, and protected by server-enforced Firebase roles.
- Parsing and chunks preserve table interpretation context and provenance.
- BM25 and local semantic retrieval are independently evaluated over 20–30 labeled questions.
- Numeric benefits are extracted, human-verified, and measured for accuracy.
- Answers cite the source plan and section/page when available; unsupported, ambiguous, unverified, or conflicting claims abstain or request clarification.
- Initial answer behavior works without Gemini; later Gemini phrasing remains optional and evidence-bound.
- Basic diagnostics are visible to users, advanced diagnostics to admins.
- README reports setup, free deployment limitations, chunking/retrieval/extraction decisions and measurements, and budget tradeoffs.
