# SBC RAG Assistant Architecture

## Purpose and status

The demo is being developed against the six PDFs currently supplied in `data/source-documents/received/` as a provisional corpus. Their SBC status and public availability are unverified; preserve accurate document labels and do not claim they are verified SBCs. Core requirements are correctness, traceable citations, table fidelity, and abstention when evidence is insufficient. Final qualification of exactly six public medical SBCs spanning HMO/PPO/HDHP remains **TBD**. The repository has a React/Vite frontend, FastAPI API, Neon schema migrations, admin upload/review screens, and a local pdfplumber ingestion/chunking pipeline. Retrieval and evidence-backed answer generation are not implemented yet.

Six supplied PDFs are stored in `data/source-documents/received/` and are the provisional development corpus. Based on current metadata and inspection, they include plan/benefit summaries and dental and vision summaries; they have not been established as standardized medical SBCs, and their public source URLs are unknown. The provisional corpus change authorizes development and provisional measurements using these files; it does not change their factual status. No HDHP SBC has been identified. Final qualifying SBC membership remains **TBD**.

The received-file metadata manifest is [`data/source-documents/received/metadata.json`](data/source-documents/received/metadata.json). It records provisional identities, file sizes and checksums, available dates/page counts, and explicit nulls for unknown values. These records do not establish public availability or SBC eligibility; verify both independently before adding a document to the active corpus.

Use all six supplied files for development and provisional evaluation, including parser inspection, table handling, chunking, extraction, retrieval, and answer-flow work. Label results as provisional and corpus-scoped. Do not infer SBC status or public availability from processing, review approval, or filenames. If a qualifying public-SBC corpus is later selected, re-run corpus-specific evaluation before claiming final SBC performance.

### Received candidate inventory

| Received file | Provisional identity | Corpus status |
|---|---|---|
| `Aetna OAMC Plan Summary  01.01.2017.pdf` | Aetna Open Access Managed Choice POS medical plan summary, effective 2017-01-01 | Inspected; appears not to be a standardized SBC |
| `Aetna HMO Plan Summary 01.01.2017.pdf` | Aetna HMO medical plan summary, effective 2017-01-01 | Inspected; appears not to be a standardized SBC |
| `Kaiser HMO Plan Summary 2017.pdf` | Kaiser Permanente Traditional Plan benefit summary, 2017 | Inspected; explicitly a benefit summary |
| `Kaiser WA.pdf` | Group Health Cooperative Multisite Benefit Summary, effective 2017-01-01 | Inspected; explicitly a benefit summary |
| `Guardian Dental PPO Plan Summary 2017.pdf` | Guardian DentalGuard Preferred PPO dental benefit summary, 2017 | Inspected; dental-only, outside intended medical SBC corpus |
| `Guardian VSP Vision Plan Summary 2017.pdf` | Guardian VSP vision benefit summary, 2017 | Inspected; vision-only, outside intended medical SBC corpus |

## Technology decisions

- **Backend/API:** Python 3.11 + FastAPI. Python supports the parser, retrieval, extraction, and local embedding libraries; FastAPI provides request validation and a clear boundary for server-side authentication/authorization.
- **Frontend:** React + TypeScript + shadcn/ui, deployed as a Render static site and calling FastAPI over HTTP.
- **Identity and roles:** Firebase Authentication Spark. Users can register and authenticate with email/password. The browser sends a Firebase ID token; FastAPI verifies it on every protected call. Admin status is a Firebase custom claim managed with the trusted local `python -m app.admin_claims grant|revoke <email>` command and checked server-side for admin routes.
- **Database:** Neon Postgres Free. `backend/migrations/001_initial_schema.sql` defines the initial plan/document/page/chunk/benefit/embedding tables. Embedding values are ordinary PostgreSQL `DOUBLE PRECISION[]` records; the migration does not enable pgvector. Browser code never receives Neon credentials. Apply migrations with `python -m app.db.migrate`; API/database repository integration remains pending.
- **Keyword retrieval:** BM25 using `rank-bm25`, independently measurable over canonical chunks.
- **Semantic retrieval:** Generate document embeddings with configurable `sentence-transformers/all-MiniLM-L6-v2` in the local ingestion CLI; generate each query embedding in the FastAPI service using the same model version. Persist approved document embeddings with model/version and chunk IDs in Neon as ordinary application data. The API builds an in-memory FAISS index from approved embeddings at startup and refreshes/rebuilds it after approval changes. No embedding API or pgvector index is used in the initial implementation. FAISS result IDs map back to canonical chunks/provenance in Neon. Verify that the deployed API can load the model and index within its memory/startup limits.
- **Vector-backend scope:** The requested comparison is BM25 versus semantic retrieval. Use FAISS as the one semantic search implementation; do not add Chroma or pgvector in parallel unless a later requirement or measured limitation justifies a documented change.
- **Chunking:** Compare fixed-size chunks with semantic/section-aware chunks. Preserve each table row and the header/plan/network context needed to interpret it. Select using labeled retrieval results, not intuition alone.
- **Experiment matrix:** Retrieval method and chunking strategy are separate variables: evaluate BM25 and semantic vector search over each of the two chunk sets (four combinations) using the same question set. Store both chunk sets with a strategy/version key, not separate copies of the source or benefit records.
- **Answers, initial implementation:** Deterministic response formatting for structured numeric facts and comparisons, plus clarification and abstention. Gemini is not integrated or called in this phase.
- **Answers, later optional phase:** Gemini may be added only after the deterministic answer path is implemented and evaluated. It may phrase backend-validated answer content, but cannot select facts, create or alter citations, fill evidence gaps, or override abstention. The application remains usable when Gemini is unavailable or disabled.
- **Deployment:** Root `render.yaml` defines a Render Free static frontend and FastAPI web service. Neon and Firebase remain external services configured manually. Render's web service may sleep after inactivity and has an ephemeral filesystem; all durable records and files therefore live outside Render. First request after sleep may take about a minute.
- **No-card cost constraint:** Target only free/no-payment-method plans, no custom domain, no SMS authentication, no paid model/API, and no paid persistent disk. Provider quotas, account verification, availability, and plan terms can change; confirm before deployment. A free tier is not an uptime guarantee.

## Corpus and ingestion flow

### Real admin upload and processing

1. An admin uploads a PDF and descriptive metadata in React.
2. FastAPI verifies the Firebase ID token and admin claim, checks the PDF signature and a 15 MB default upload limit (`MAX_UPLOAD_BYTES` can override it), and stores the original PDF and upload record in Neon. Status begins as `uploaded`; `corpus_status` remains `candidate`.
3. A local ingestion CLI (`python -m app.ingest`), run by the project maintainer, fetches uploaded PDFs from Neon. pdfplumber extracts page text and table cells; table headers and rows are stored in `document_pages.tables_json`. It creates both fixed-size and section-aware chunks with table rows kept intact and page/section/table-row provenance in `chunks.provenance`.
4. The ingestion process records unreadable-page or parser errors and moves the document to `needs_review`; extracted benefit records remain unverified.
5. An admin inspects parsed pages/chunks and approves or rejects the document. This review status is separate from SBC qualification: approval allows a document into the provisional development corpus but does not establish SBC status or public availability. Benefit values have their own review state. Only approved documents/chunks and verified benefit values may enter normal answer retrieval.

This is a genuine upload and ingestion workflow. PDF parsing and document-embedding generation consume the maintainer's local CPU/RAM when the CLI runs. At query time, the deployed FastAPI service embeds the question locally, searches its in-memory FAISS index, and fetches matching approved chunks/provenance from Neon. It loads the sentence-transformer model and approved embeddings on startup, and refreshes the index after approval changes. Render restarts/cold starts therefore reconstruct the index from Neon, without relying on the maintainer's computer. Verify that the model and index fit the selected API service's memory and startup limits. Keep upload size/corpus limits within Neon Free storage/egress quotas. If documents outgrow Neon storage, evaluate a no-card object-storage service before changing the design.

### Parsing, provenance, and data records

For every document retain stable document and plan IDs, insurer, plan name/type/year, verified public source URL, original filename, upload/approval state, and document checksum. Public availability and SBC status must be established before it counts toward the six-SBC requirement.

For parsed pages/rows/chunks retain document/plan IDs, stable record IDs, page, section heading when detectable, table and row context, parse status, and chunk strategy/version. Each table row must stay intact with sufficient headers/context; mark unavailable provenance rather than inventing it.

Structured benefit records store the value exactly as stated, category, plan/document identity, network and individual/family distinctions when present, source section/page/row, reviewer status, and missing/ambiguous/conflicting status. Initial categories are deductible, ER cost sharing, copays, and out-of-pocket maximum. Missing data is never represented as zero.

The current Phase 3 implementation prefers detected table rows, falling back to page text where tables are unavailable, to create review candidates for those four categories when a plausible amount or percentage is present. It preserves the full source row as `value_text`, page/section provenance, and recognizable dimensions; distinct values in one row are marked ambiguous. This conservative helper is not a substitute for table-aware human review and does not verify values. Admin-only `/api/admin/benefits` endpoints and the Benefits review page support extraction, inspection, correction, dimension editing, and explicit status changes. Only Phase 5 may expose `verified` values to answers, and only for approved documents. Measure extraction quality against manually checked labels from the provisional corpus and label results accordingly.

## Retrieval and question-answer flow

```text
Browser -> Firebase sign-in -> ID token -> FastAPI
  -> verify token and (for admin routes) admin claim
  -> resolve requested plan(s); ask clarification if ambiguous
  -> numerical question: query verified structured benefit records
  -> broader coverage question: retrieve using BM25 and/or FAISS semantic search (query embedding generated locally by FastAPI)
  -> verify source support, plan match, consistency, and usable provenance
  -> insufficient/ambiguous/conflicting evidence: abstain or clarify
  -> otherwise deterministic formatting (initial implementation; optional Gemini phrasing only in a later phase)
  -> validate answer citations against supporting records
  -> response with answer/status/citations/diagnostics
```

BM25 and FAISS semantic search run independently in evaluation across both chunking strategies. The evaluation playground is admin-only and lets admins explicitly select a retrieval method and chunking strategy to compare behavior and inspect detailed rank/score output. Ordinary users see basic answer diagnostics only; ordinary query mode uses the configuration selected from measured results, and runtime fusion is not assumed. Numerical comparisons use structured verified records as their source of truth and may use retrieved SBC rows as corroboration. Comparisons must preserve comparable dimensions (e.g. in-network vs out-of-network, individual vs family). If dimensions differ or are unclear, explain the distinction or abstain rather than collapsing values.

Every factual answer cites plan and SBC section, adding page when available. The initial implementation has no LLM call. If Gemini is added later, the evidence gate precedes it, citations must resolve to records supplied to the phrasing step, and a post-generation check rejects unsupported claims or returns abstention.

## Interface and diagnostics

The signed-in frontend has a page-flow skeleton: all users can navigate to Plans, Chat (the default home page), and Profile; users with the Firebase admin claim also see the Playground and Evaluation pages. The claim controls navigation visibility only and does not grant API access. Upload/review, retrieval experiments, evaluation runs, profile edits, and account deletion are placeholders until their backed workflows are implemented.

The chat page has a roomy transcript, composer, starter prompts, and a new-chat action. Displayed turns are held in frontend memory for the active page session only and clear on new chat, sign-out, reload, or page close. Live message text is not saved to Neon, local storage, session storage, or the evaluation manifest. At this stage, each submitted question is sent independently; prior turns are displayed but are not included as context in later API requests. Evaluation questions remain separately authored test data; persisted evaluation records contain results/metrics without ordinary live query text.

Logical API responses distinguish `answered`, `insufficient_evidence`, and `clarification_needed`, include a concise answer when supported, and carry citations. The scaffold exposes `GET /api/health` and protected `POST /api/chat`; chat currently returns a deterministic insufficient-evidence response until the provisional corpus and retrieval pipeline are connected. The frontend uses Firebase email/password sign-in and sends an ID token as a bearer token. FastAPI verifies the token server-side and fails closed when Firebase credentials are not configured.

All authenticated users see basic diagnostics: resolved plan names, answer/abstention status, cited sources, and a concise indication of the evidence path (structured lookup or retrieval). The admin-only evaluation playground exposes selectable BM25/vector and fixed-size/semantic-section-aware configurations. Admins also see ranked retrieved chunks, scores, parse/extraction/review status, ingestion errors, embedding/index versions, and evidence-gate details. Never expose credentials, tokens, privileged configuration, or raw internal stack traces.

## Evaluation and open implementation checks

Maintain 20–30 questions with verified answers and supporting source locations. Measure all four BM25/vector × fixed-size/semantic-section-aware combinations independently by question type, plus extraction accuracy against manual verification, answer accuracy, and latency. Token usage is deferred until optional Gemini phrasing is enabled. Live chat transcripts exist in frontend memory only and are not retained after the active page session; evaluation manifest questions are separately authored test data and live queries are never added to that manifest. Document actual results and limitations in README; do not invent baselines.

Before treating final SBC acceptance as met, verify six publicly available standardized medical SBCs with HMO/PPO/HDHP coverage. For the provisional corpus, validate actual document identities and retain unverified SBC/public-source labels. Also verify the deployed API can build/refresh its in-memory FAISS index from approved embedding records in Neon; the selected sentence-transformer model fits local ingestion; Neon storage fits PDFs plus derived data; Render/Firebase/Neon no-card plans remain available to the account; and upload/admin/local-ingestion-to-review flow works end to end.

The qualifying public-SBC corpus is an open final-acceptance prerequisite. Development and provisional evaluation use the six received files and do not depend on resolving that prerequisite first. Remaining implementation settings (API routes, table schema, chunk sizes, retrieval top-k, evidence thresholds, upload byte limit, and model/version measurements) should be set during implementation/evaluation and recorded without weakening provenance or abstention requirements.
