# Implementation Plan: SBC RAG Demo

This plan records the agreed technology direction and tracks implementation. The six received PDFs are approved as a provisional development/evaluation corpus, but remain unverified as SBCs and as publicly sourced documents. Phase 1's local frontend/API scaffold, Firebase auth foundation, initial Neon schema migration, and Render Blueprint are implemented. Phase 2 upload, local parsing, chunking, and inspection workflows are implemented; real database ingestion and corpus review remain to be run. Phase 3 benefit extraction and review scaffolding is implemented on top of parsed pages. Phase 4 retrieval and evaluation tooling is implemented, while labeled runs remain pending. Phase 5's deterministic answer and session-only follow-up flow is implemented in code; end-to-end corpus review and measured answer quality remain pending.

## Selected stack

- **Runtime/API:** Python 3.11 and FastAPI for ingestion commands, retrieval, answer logic, and the authenticated HTTP API.
- **Frontend:** React + TypeScript with shadcn/ui; serve as a Render static site and call the FastAPI API.
- **Authentication/roles:** Firebase Authentication on the no-cost Spark plan for email/password or social login. FastAPI verifies ID tokens for every protected request. A local one-time admin bootstrap command assigns Firebase custom claims; no public self-promotion endpoint.
- **Persistent data:** Neon Postgres Free for plan/document metadata, uploaded PDF bytes, parsed pages/rows/chunks, verified structured benefit records, provenance, ingestion state, and evaluation results. Use ordinary SQL access through a repository/data-access layer; do not expose Neon credentials to the browser.
- **Semantic retrieval:** Generate document embeddings with `sentence-transformers/all-MiniLM-L6-v2` in the local ingestion CLI and query embeddings in the FastAPI process, using the same configurable model version. Persist approved document embedding values as ordinary per-chunk data in Neon; Neon does not perform vector search and pgvector is not used. The API currently builds an in-memory FAISS index for each semantic request, so approval changes apply on the next search. A startup cache may be added after latency and memory measurements. No embedding API or shared filesystem is required. Verify that the selected Render service can load the model and index within its memory/startup limits.
- **Keyword retrieval:** `rank-bm25` over the same canonical chunks, independently measurable from semantic search.
- **PDF handling:** `pdfplumber` first; evaluate actual SBC output and add Camelot only for tables where it demonstrably improves row/cell structure.
- **Answers, initial phase:** Deterministic formatting for structured numeric lookups and comparisons, citations, clarification, and abstention. Do not integrate Gemini in the initial implementation.
- **Answers, later phase:** Gemini may be added as an optional final phrasing adapter only after the deterministic answer path is implemented and evaluated. It receives validated facts/evidence and cannot choose values, create citations, fill missing evidence, or override abstention. Do not make initial completion dependent on Gemini or a free tier.
- **Deployment:** Render Free static site + web service; Neon and Firebase are external managed services. Expect API sleep/cold starts and ephemeral Render filesystems. Store durable state in Neon. Do not require a custom domain or paid persistent disk.
- **Uploaded source files:** Store modest PDFs as PostgreSQL binary data in Neon for the initial six-plan demo to avoid another account/service and keep uploads durable. Impose a documented upload-size limit below provider/request limits. If corpus size outgrows database storage, revisit object storage only after verifying a no-card option.
- **Ingestion execution:** Admin upload through the deployed UI is real and durable. Parsing/chunking runs through the local ingestion CLI; approved document chunks are embedded with the separate local `python -m app.embed` command. Parsed provenance and embedding records are stored in Neon. Admin approval is required before chunks enter retrieval. No uploaded file or generated index depends on Render's ephemeral filesystem.
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

- **Completed project setup:** Six PDFs have been received, provisionally classified in `ARCHITECTURE.md`, and recorded with available file identity/provenance fields in `data/source-documents/received/metadata.json`. Unknown metadata remains null; the files are the provisional development corpus but remain unverified as SBCs/public sources.
- **Scaffold added:** React + TypeScript + Vite frontend with Firebase email/password registration/sign-in, admin document upload/review, benefit review, retrieval playground, and evaluation controls. Admin navigation reads the Firebase custom claim for presentation; server authorization remains authoritative. FastAPI chat now uses approved provisional evidence and verified benefit records for deterministic answers.
- [x] Establish a small Python backend and React TypeScript frontend layout; ingestion/evaluation/test directories will be added with those phases.
- [x] Add dependency/configuration files, local development instructions, `.env.example` containing names only, and ignores for secrets/build outputs.
- [x] Add Firebase registration/sign-in and FastAPI ID-token verification; Neon relational schema/migration with ordinary embedding values and no pgvector; FastAPI health/API skeleton; local admin-claim bootstrap command; and Render Blueprint without embedded secrets. Protect each authenticated/admin route when it is introduced.
- [x] Document local run and Render deployment setup, including manual provider configuration, cold starts, and free-tier limits.

**Milestone:** Phase 1 implementation is complete. Local commands and deployment configuration are documented. A real deployment still requires Firebase/Neon/Render accounts, credentials, and the manual environment settings in README; external resources have not been provisioned from this repo.

### Provisional corpus and final SBC qualification

- [x] Use the six received PDFs as the active provisional development/evaluation corpus; preserve their actual document type and their unverified SBC/public-source status.
- [x] Keep provisional corpus membership distinct from SBC qualification. The set includes dental and vision summaries and has not been established as six standardized medical SBCs.
- [ ] Resolve final corpus qualification as exactly six public medical SBCs spanning HMO/PPO/HDHP, or document a later approved change to that target. This does not block development or provisional evaluation.

**Milestone:** The six supplied files are used as a clearly labeled provisional corpus. Final SBC/public-source qualification remains an open acceptance item.

### Phase 2 — SBC parsing, provenance, and table-safe chunks

- [x] Build source-document registry and real admin PDF upload, storing original PDFs and upload status in Neon.
- [x] Implement the local ingestion CLI: fetch pending uploads, parse pages/tables with pdfplumber, preserve section/page and table headers, and report parse issues.
- [x] Keep documents and extracted records in pending/review states until an admin approves them; upload leaves documents in `uploaded`, and ingestion moves them to `needs_review`.
- [x] Compare fixed-size chunking with semantic/section-aware chunking while never splitting a table row from its interpretive headers/context.
- [ ] Review parser output on all six provisional documents; add Camelot only where it improves table fidelity. If a qualifying SBC corpus is later selected, repeat corpus-specific parser review.
- [x] Add parser/chunker fixtures covering provenance, intact rows, missing sections, and malformed PDF input.

**Milestone:** Upload, local parsing/chunking, inspection, and document review work for the provisional corpus. Review the parsed output on each supplied document before relying on it for provisional evaluation.

### Phase 3 — Structured benefit extraction and admin review

- [x] Define typed candidate records for deductible, ER cost sharing, copays, and out-of-pocket maximum, preserving source wording, available page/section, and recognizable network/family/individual/coinsurance dimensions.
- [x] Add conservative candidate extraction that prefers detected table rows and uses page text where tables are unavailable. Candidates remain `pending_review` (or `ambiguous` where a source row contains distinct values); this is a review aid, not an authoritative parser.
- [x] Add admin-only API operations and a benefit review UI to extract, inspect, correct, and assign review status, with reviewer UID and timestamp.
- [x] Add an idempotency index for repeated extraction of the same source line.
- [x] Gate answer queries on verified benefit values and approved document evidence. End-to-end corpus review remains open.
- [ ] Measure extraction accuracy against manually verified labels for the provisional corpus, reporting it as corpus-scoped; repeat on any later qualifying SBC corpus.

**Milestone:** Extraction and admin review are implemented, and Phase 5 now applies the review gate. Measured accuracy must identify the provisional corpus.

### Phase 4 — BM25 and semantic retrieval baselines

- [x] Implement local sentence-transformer embedding generation for approved chunks and persist vectors with chunk IDs/model version in Neon; construct the FAISS index in the API process from approved embeddings for semantic searches.
- [x] Add plan/document/section filtering without losing provenance.
- [ ] Create 20–30 evaluation questions with manually checked expected evidence locations, answer labels, and question types drawn from the six provisional documents; label results provisional and corpus-scoped. The manifest and runner are in place, but labels must be authored after reviewing actual ingested documents.
- [x] Implement four-combination evaluation over the same manifest and persist aggregate/per-question metrics without retaining question text.
- [x] Add an admin-only evaluation playground for selecting BM25 or semantic search and fixed-size or semantic/section-aware chunks, plus detailed ranked evidence traces.
- [x] Record latency and retrieval scores per question/configuration, retaining both methods for comparison.
- [ ] Select runtime retrieval behavior from measured results. Ordinary chat temporarily defaults to BM25 with section-aware chunks until labeled runs exist.

**Milestone:** Retrieval, playground, and reproducible evaluation runner are implemented. Provisional retrieval findings remain pending reviewed parser output, the 20–30 manually labeled questions, and actual runs.

### Phase 5 — Authenticated answer flow and diagnostics

- [x] Require Firebase token verification on protected FastAPI requests and admin custom claims on upload/review/evaluation/diagnostic endpoints. Targeted authorization review remains open.
- [x] Send the previous in-memory question and resolved plan IDs for short follow-ups. New chat, sign-out, and reload clear this context; no chat-history persistence or history API was added.
- [x] Resolve approved plans and ask for clarification for ambiguous names.
- [x] Route numerical lookups and comparisons through verified structured records; quote retrieved, provenance-bearing source rows for broader coverage questions.
- [x] Apply approval, review, value, dimension, conflict, and citation gates with explicit clarification or abstention.
- [x] Implement deterministic, cited answer formatting without Gemini. Measured answer accuracy remains pending the labeled manifest and reviewed corpus.
- [x] Show basic diagnostics to all users; show admins detailed answer traces and document/parse/benefit/embedding health.
- [ ] Use measured results to select ordinary-user defaults; retain explicit configuration selection in the evaluation playground.
- [ ] Add tests for authentication, admin authorization, comparisons, citations, ambiguity, missing/conflicting evidence, and uploaded-document approval state.

**Milestone:** The Phase 5 flow is implemented in code. End-to-end review against actual ingested documents, targeted tests, and measured answer accuracy remain open before treating the milestone as validated.

### Phase 6 — Deployment, evaluation, and documentation

- [ ] Deploy React static site and FastAPI web service on Render Free; configure Firebase authorized domains and server secrets; connect Neon Free.
- [ ] Ensure the review UI communicates backend cold start and retries safely; verify upload-to-local-ingestion-to-review-to-answer lifecycle.
- [ ] Run the labeled set against the provisional corpus; report answer/extraction accuracy, per-method retrieval results by question type, and latency, clearly scoped to those documents. Defer token usage reporting until optional Gemini phrasing is enabled.
- [ ] Document actual chunking/parser/vector choices and observed limits, free-tier behavior, results, and what additional budget would change.

**Milestone:** The deployed demo is reproducible within no-card free-tier constraints and reports measured evidence quality.

### Later optional phase — Gemini phrasing

- [ ] Only after the initial answer flow is complete, deployed, and evaluated, optionally add Gemini behind an adapter to phrase validated answer content.
- [ ] Verify the Gemini path preserves backend-selected facts, citations, and abstention, and compare quality/latency/token use with deterministic output.
- [ ] Keep the application fully functional with Gemini disabled or unconfigured.

## Definition of done

- The six received files are the active provisional corpus, with document types and unverified SBC/public-source status represented accurately. Final six-public-SBC qualification remains TBD.
- Admin uploads are durable; ingestion is real, locally executed, reviewable, and protected by server-enforced Firebase roles.
- Parsing and chunks preserve table interpretation context and provenance.
- BM25 and local semantic retrieval are independently evaluated over 20–30 labeled questions.
- Numeric benefits are extracted, human-verified, and measured for accuracy.
- Answers cite the source plan and section/page when available; unsupported, ambiguous, unverified, or conflicting claims abstain or request clarification.
- Initial answer behavior works without Gemini; later Gemini phrasing remains optional and evidence-bound.
- Basic diagnostics are visible to users, advanced diagnostics to admins.
- README reports setup, free deployment limitations, chunking/retrieval/extraction decisions and measurements, and budget tradeoffs.
