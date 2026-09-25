# Implementation Plan: SBC RAG Demo

This plan records the agreed technology direction and tracks implementation. The six received PDFs are approved as a provisional development/evaluation corpus, but remain unverified as SBCs and as publicly sourced documents. Phase 1's frontend/API scaffold, Firebase auth foundation, Neon migrations, and Render Blueprint are implemented. Phase 2 upload, parsing, chunking, inspection, and automatic API-triggered ingestion are implemented in code; deployed resource qualification and full corpus review remain pending. Phase 3 benefit extraction and review scaffolding is implemented on top of parsed pages. Phase 4 retrieval and evaluation tooling is implemented, while labeled runs remain pending. Phase 5's deterministic answer and session-only follow-up flow is implemented in code; measured answer quality remains pending.

Evidence review fixes retain every extracted table row, exclude ineligible documents from retrieval, require usable benefit sections, and abstain when requested candidates are ambiguous or conflicting. Numeric lower/higher comparisons identify an outcome only for comparable values, and mixed coverage types require clarification. The parser orders table rows and text by page position, assigns row section and network context from detected preceding headings, and filters table-positioned text from chunks. Existing stored chunks need re-ingestion to use the revised parser; existing verified benefits need section review after migration `006`. Semantic paraphrase matching remains constrained by the source-row term gate until labeled corpus evaluation supports a safe broader rule.

The FastAPI service now triggers the same parsing, chunking, candidate extraction, embedding, and readiness pipeline after an admin upload or Retry. Neon stores queued work; startup and admin document refresh resume interrupted jobs, with at most two automatic attempts before a visible failure. The local `python -m app.pipeline` command remains available for maintenance. `ready` and `ready_with_warnings` are queryable after all stages complete and both chunk strategies have usable embeddings. Isolated issues remain visible as warnings; critical failures stay unavailable. Prior `approved` documents remain queryable. Migration `008` adds the durable queue marker and attempt count. Full-corpus processing and Render memory qualification remain pending.

## Selected stack

- **Runtime/API:** Python 3.11 and FastAPI for ingestion commands, retrieval, answer logic, and the authenticated HTTP API.
- **Frontend:** React + TypeScript with shadcn/ui; serve as a Render static site and call the FastAPI API.
- **Authentication/roles:** Firebase Authentication on the no-cost Spark plan for email/password or social login. FastAPI verifies ID tokens for every protected request. A local one-time admin bootstrap command assigns Firebase custom claims; no public self-promotion endpoint.
- **Persistent data:** Neon Postgres Free for plan/document metadata, uploaded PDF bytes, parsed pages/rows/chunks, structured benefit candidates and reviews, provenance, processing state, and evaluation results. Do not expose Neon credentials to the browser.
- **Semantic retrieval:** Generate document and query embeddings with `sentence-transformers/all-MiniLM-L6-v2` in the FastAPI service, using the same configurable model version. The local maintenance command uses that same pipeline. Persist queryable document embedding values as ordinary per-chunk data in Neon; Neon does not perform vector search and pgvector is not used. The API currently builds an in-memory FAISS index for each semantic request. No embedding API or shared filesystem is required. Render memory fit remains **TBD** after a local macOS embedding run for one PDF exceeded the free service's 512 MiB limit.
- **Keyword retrieval:** `rank-bm25` over the same canonical chunks, independently measurable from semantic search.
- **PDF handling:** `pdfplumber` first; evaluate actual SBC output and add Camelot only for tables where it demonstrably improves row/cell structure.
- **Answers, initial phase:** Deterministic formatting for structured numeric lookups and comparisons, citations, clarification, and abstention. Do not integrate Gemini in the initial implementation.
- **Answers, later phase:** Gemini may be added as an optional final phrasing adapter only after the deterministic answer path is implemented and evaluated. It receives validated facts/evidence and cannot choose values, create citations, fill missing evidence, or override abstention. Do not make initial completion dependent on Gemini or a free tier.
- **Deployment:** Render Free static site + web service; Neon and Firebase are external managed services. Expect API sleep/cold starts and ephemeral Render filesystems. Store durable state in Neon. Do not require a custom domain or paid persistent disk.
- **Uploaded source files:** Store modest PDFs as PostgreSQL binary data in Neon for the initial six-plan demo to avoid another account/service and keep uploads durable. Impose a documented upload-size limit below provider/request limits. If corpus size outgrows database storage, revisit object storage only after verifying a no-card option.
- **Ingestion execution:** An admin upload or Retry queues a document in Neon and schedules the full pipeline after the FastAPI response. A database advisory lock serializes processing; startup and admin document refresh resume interrupted work. Two interrupted attempts stop automatic retries and require admin Retry. Render sets the configurable embedding batch size to 1 to reduce peak memory. `python -m app.pipeline`, `app.ingest`, and `app.embed` remain maintenance commands. Parsed provenance, stage outcomes, warnings, and embeddings are stored in Neon. No uploaded file or generated index depends on Render's ephemeral filesystem.
- **Evaluation/tests:** pytest for backend/parser/retrieval/auth/citation/evidence behavior; frontend checks as appropriate. Store a versioned 20–30 question evaluation manifest with verified expected values and source locations. Record accuracy, latency, retrieval results by method/question type, and extraction accuracy. Defer token usage measurement until optional Gemini synthesis is enabled.
- **Secrets:** Environment variables for Neon connection string, Firebase project/service credentials, and deployment configuration. Privileged Firebase credentials exist only in local admin tooling or protected server secrets; never in React or source control.

## Retrieval and chunking experiment

- The two retrieval methods are **BM25 keyword retrieval** (`rank-bm25`) and **semantic vector retrieval** (local sentence-transformer embeddings searched with local FAISS). These methods differ in how they find relevant chunks; neither replaces the other in the baseline evaluation.
- The two chunking strategies are **fixed-size chunking** and **semantic/section-aware chunking**. Both must preserve table rows and the headers/context needed to interpret them.
- Evaluate the four combinations (BM25 + fixed-size, BM25 + semantic/section-aware, vector + fixed-size, vector + semantic/section-aware) against the same labeled questions and report retrieval/answer results by question type.
- Add an **admin-only evaluation playground** that lets an admin select a retrieval method and chunking strategy, then submit a question and inspect answer status, citations, and diagnostics. This is an evaluation control, not an unreviewed production routing knob: ordinary user mode uses the measured default configuration; admins can compare configurations and inspect detailed scores/run traces.
- Store versioned chunks for both strategies and associate each retrieval run with its chunking strategy, retrieval method, model/version, and top-k/configuration so results are reproducible. Do not duplicate original PDFs or verified benefit records for each strategy.
- Numerical questions use unambiguous, cited structured candidates or explicitly verified records; selected retrieval/chunking settings affect source-evidence retrieval and diagnostics.

## Ordered implementation phases

### Phase 1 — Corpus and runnable project skeleton

- **Completed project setup:** Six PDFs have been received, provisionally classified in `ARCHITECTURE.md`, and recorded with available file identity/provenance fields in `data/source-documents/received/metadata.json`. Unknown metadata remains null; the files are the provisional development corpus but remain unverified as SBCs/public sources.
- **Scaffold added:** React + TypeScript + Vite frontend with Firebase email/password registration/sign-in, a combined admin Plans/document upload and diagnostics page, optional benefit review, retrieval playground, and evaluation controls. Admin navigation reads the Firebase custom claim for presentation; server authorization remains authoritative. FastAPI chat uses queryable provisional evidence and supported benefit records for deterministic answers.
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
- [x] Keep uploads unavailable until the full pipeline marks them `ready` or `ready_with_warnings`; explicit admin verification remains optional.
- [x] Compare fixed-size chunking with semantic/section-aware chunking while never splitting a table row from its interpretive headers/context.
- [ ] Review parser output on all six provisional documents; add Camelot only where it improves table fidelity. If a qualifying SBC corpus is later selected, repeat corpus-specific parser review.
- [x] Add parser/chunker fixtures covering provenance, intact rows, missing sections, and malformed PDF input.

**Milestone:** Upload, local parsing/chunking, inspection, and document review work for the provisional corpus. Review the parsed output on each supplied document before relying on it for provisional evaluation.

### Phase 3 — Structured benefit extraction and admin review

- [x] Define typed candidate records for deductible, ER cost sharing, copays, and out-of-pocket maximum, preserving source wording, available page/section, and recognizable network/family/individual/coinsurance dimensions.
- [x] Add table-aware candidate extraction that carries benefit labels and period context across continuation rows, separates individual/family and network values, and keeps all candidates pending review. Page text remains a fallback where tables are unavailable; extraction remains a review aid, not an authoritative parser.
- [x] Add regression coverage for the Aetna out-of-pocket maximum table, multi-network continuation rows, values combined in one cell, and repeated headerless table cells.
- [x] Add admin-only API operations and a benefit review UI to extract, inspect, correct, and assign review status, with reviewer UID and timestamp.
- [x] Add an idempotency index for repeated extraction of the same source line.
- [x] Gate answers on queryable documents and unambiguous values with page and section citations; admin verification remains optional. End-to-end corpus evaluation remains open.
- [ ] Measure extraction accuracy against manually verified labels for the provisional corpus, reporting it as corpus-scoped; repeat on any later qualifying SBC corpus.

**Milestone:** Automatic extraction and optional admin review are implemented. Measured accuracy must identify the provisional corpus.

### Phase 4 — BM25 and semantic retrieval baselines

- [x] Implement local sentence-transformer embedding generation for queryable chunks and persist vectors with chunk IDs/model version in Neon; construct the FAISS index in the API process from current embeddings for semantic searches.
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
- [x] Resolve queryable plans and ask for clarification for ambiguous names.
- [x] Route numerical lookups and comparisons through supported structured records; quote retrieved, provenance-bearing source rows for broader coverage questions.
- [x] Apply readiness, value, dimension, conflict, and citation gates with explicit clarification or abstention.
- [x] Implement deterministic, cited answer formatting without Gemini. Measured answer accuracy remains pending the labeled manifest and reviewed corpus.
- [x] Show basic diagnostics to all users; show admins detailed answer traces and document/parse/benefit/embedding health.
- [ ] Use measured results to select ordinary-user defaults; retain explicit configuration selection in the evaluation playground.
- [x] Add targeted tests for readiness, warning and critical outcomes, supported candidate answers, affected-question abstention, and admin stage diagnostics. Broader corpus evaluation remains open.

**Milestone:** The Phase 5 flow is implemented in code. End-to-end review against actual ingested documents, targeted tests, and measured answer accuracy remain open before treating the milestone as validated.

**Kaiser parsing and answer repair (2026-09-25):** Recognized the Traditional Plan PDF's title-case benefit headings, carried sections into text candidates and table rows, stored text wording in chunk provenance, and accepted the source's literal `None` deductible without converting it to zero. Plan and drug deductible rows are distinguished. A PDF-to-BM25-to-answer regression covers cited urgent-care, emergency-department, and deductible answers plus abstention for missing out-of-network evidence. The configured Neon uploads were reprocessed: the Traditional Plan document is `ready` with no warnings; the separate Kaiser WA document is `ready_with_warnings` because 18 candidates remain ambiguous and 17 lack a detected section. Both now return BM25 evidence. Backend deployment and broader provisional-corpus accuracy measurement remain pending.

**Automatic ingestion (2026-09-25):** New admin uploads and Retry now start the existing pipeline in a FastAPI background task. Neon records queued work and attempts; startup and document-list requests recover interrupted work, and a database advisory lock limits ingestion to one document at a time. Migration `008` was applied to the configured development Neon database. A disposable Guardian vision upload through the authenticated API path completed all four stages, produced 13 chunks, reached `ready_with_warnings`, and was removed afterward. A repeat with Render's batch-size-1 setting also reached `ready_with_warnings`; both temporary uploads and plans were removed. Backend tests and the frontend build passed. Render deployment and its 512 MiB memory fit remain unverified; the batch-size-1 local API run peaked at about 555 MiB.

### Phase 6 — Deployment, evaluation, and documentation

- [ ] Deploy React static site and FastAPI web service on Render Free; configure Firebase authorized domains and server secrets; connect Neon Free.
- [ ] Verify upload-to-automatic-pipeline-to-answer against Neon and on the deployed Render service; measure peak memory, CPU time, and cold-start behavior. Render Free compatibility is **TBD** because the current local embedding path exceeded 512 MiB even at batch size 1.
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
- Numeric benefits are extracted with traceable provenance; optional human verification and measured accuracy remain available.
- Answers cite the source plan and section/page when available; unsupported, ambiguous, untraceable, or conflicting claims abstain or request clarification.
- Initial answer behavior works without Gemini; later Gemini phrasing remains optional and evidence-bound.
- Basic diagnostics are visible to users, advanced diagnostics to admins.
- README reports setup, free deployment limitations, chunking/retrieval/extraction decisions and measurements, and budget tradeoffs.
