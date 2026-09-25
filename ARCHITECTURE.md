# SBC RAG Assistant Architecture

## Purpose and status

The demo is being developed against the six PDFs currently supplied in `data/source-documents/received/` as a provisional corpus. Their SBC status and public availability are unverified; preserve accurate document labels and do not claim they are verified SBCs. Core requirements are correctness, traceable citations, table fidelity, and abstention when evidence is insufficient. Final qualification of exactly six public medical SBCs spanning HMO/PPO/HDHP remains **TBD**. The repository has a React/Vite frontend, FastAPI API, Neon schema migrations, admin upload/review screens, automatic pdfplumber ingestion/chunking, retrieval, and a deterministic answer path. Corpus review and measured quality remain pending.

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
- **Database:** Neon Postgres Free. Migrations define plan/document/page/chunk/benefit/embedding and evaluation tables. Embedding values are ordinary PostgreSQL `DOUBLE PRECISION[]` records; migrations do not enable pgvector. Browser code never receives Neon credentials. Apply migrations with `python -m app.db.migrate`.
- **Keyword retrieval:** BM25 using `rank-bm25`, independently measurable over canonical chunks.
- **Semantic retrieval:** Generate document embeddings with configurable `sentence-transformers/all-MiniLM-L6-v2` using local `python -m app.pipeline`; generate query embeddings in FastAPI with the same model/version. Persist queryable document embeddings with model/version, model-weight fingerprint, and chunk IDs in Neon as ordinary application data. The API applies identical readiness/plan/document/section/chunk-version filters to chunks and vectors, validates embedding dimension and finite nonzero values, then builds an in-process FAISS index. Readiness changes are reflected on the next search. No embedding API or pgvector index is used. FAISS results map back to canonical chunks/provenance in Neon.
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
2. FastAPI verifies the Firebase ID token and admin claim, checks the PDF signature and a 15 MB default upload limit (`MAX_UPLOAD_BYTES` can override it), and stores the original PDF and upload record in Neon. Status begins as `uploaded`; `corpus_status` remains `candidate`. A queued timestamp requests automatic processing.
3. After returning the upload response, FastAPI starts an in-process background task. A PostgreSQL advisory lock allows one ingestion run at a time across API instances and the maintenance CLI. The task fetches queued PDF bytes from Neon; pdfplumber extracts page text, table cells, and positions. Rows, header positions, labels, and section context are stored with page provenance. Both chunk strategies keep table rows intact.
4. The task extracts structured benefit candidates, creates local sentence-transformer embeddings for both chunk sets, checks that current nonzero finite vectors cover each chunk, and stores per-stage outcomes and warnings. It marks the document `ready` or `ready_with_warnings` only after all stages complete. Isolated parse or extraction issues remain warnings when other evidence is usable. Critical failures leave the document unavailable.
5. Admins inspect stages, warnings, parsed pages, chunks, and detected benefit sections. They can correct or explicitly verify a benefit and can reject or verify a ready document, but neither action is required for routine answers. Existing `approved` documents remain queryable. Readiness and approval do not establish SBC status or public availability.

The queued timestamp remains set until processing reaches a terminal state. Startup recovery and admin document refresh resume interrupted work; the attempt counter stops after two interrupted attempts and exposes a failure for admin Retry. The API and the local maintenance CLI use the same pipeline. At query time, the API embeds the question locally, loads vectors from Neon, builds an in-process FAISS index, and maps results back to provenance. No persistent vector database or separate queue service is added. The free Render service's memory fit is **TBD**: a local macOS run of the current model exceeded its documented 512 MiB limit. Keep upload size/corpus limits within Neon Free storage/egress quotas.

### Parsing, provenance, and data records

For every document retain stable document and plan IDs, insurer, plan name/type/year, verified public source URL, original filename, upload/approval state, and document checksum. Public availability and SBC status must be established before it counts toward the six-SBC requirement.

For parsed pages/rows/chunks retain document/plan IDs, stable record IDs, page, section heading when detectable, table and row context, parse status, and chunk strategy/version. Text-unit provenance stores both the source wording and its line number. Each table row must stay intact with sufficient headers/context; mark unavailable provenance rather than inventing it. Detected benefit headings take precedence over table column labels in citations; column labels remain available as fallback context when no usable benefit heading is detected.

Structured benefit records store the value exactly as stated, category, plan/document identity, network and individual/family distinctions when present, source section/page/row, reviewer status, and missing/ambiguous/conflicting status. Initial categories are deductible, ER cost sharing, copays, and out-of-pocket maximum. Missing data is never represented as zero.

The current extraction implementation reads detected table cells and nearby continuation rows, falling back to page text when tables are unavailable. It carries benefit labels and period qualifiers across continuation rows, maps network and individual/family context from cells and headers, and emits separate candidates for distinct benefit scopes. Repeated values in a headerless helper cell are removed during parsing when the adjacent labeled column contains the same value. Candidates begin in `pending_review` or `ambiguous`; `pending_review` means automatically extracted, not blocked. Admin-only `/api/admin/benefits` endpoints and the Benefits review page support extraction, inspection, correction, section/dimension editing, and explicit status changes. The answer path uses an unambiguous candidate only with a usable page and section citation, matching requested context, and no conflicting relevant value. Explicitly verified records remain usable. Measure extraction quality against manually checked labels from the provisional corpus and label results accordingly.

Reviewer confirmation of the source section is stored separately from the detected section. Ambiguous, conflicting, missing, or untraceable evidence blocks only questions that depend on it. Retrieval and embedding exclude documents marked ineligible.

## Retrieval and question-answer flow

```text
Browser -> Firebase sign-in -> ID token -> FastAPI
  -> verify token and (for admin routes) admin claim
  -> resolve requested plan(s); ask clarification if ambiguous
  -> numerical question: query supported structured benefit records
  -> broader coverage question: retrieve using BM25 and/or FAISS semantic search (query embedding generated locally by FastAPI)
  -> verify source support, plan match, consistency, and usable provenance
  -> insufficient/ambiguous/conflicting evidence: abstain or clarify
  -> otherwise deterministic formatting (initial implementation; optional Gemini phrasing only in a later phase)
  -> validate answer citations against supporting records
  -> response with answer/status/citations/diagnostics
```

BM25 and FAISS semantic search run independently in evaluation across both chunking strategies. The admin playground lets admins select a method and strategy, apply optional plan/document/section filters, and inspect detailed rank/score output. The evaluation runner can run either retrieval method independently or all four combinations. It reports evidence hit rate, MRR, and separate corpus-load, embedding-load, index-build, model/query-embedding, search, and total-request timings overall and by question type. Evaluation records snapshot queryable document IDs/checksums/review timestamps, chunk strategy versions, and semantic model identity/fingerprint. Persisted run data excludes question text. Ordinary chat temporarily uses configurable BM25 with section-aware chunks for broader questions; the measured default remains pending the labeled evaluation. Numerical comparisons use supported structured records as their source of truth. Comparisons preserve comparable network, individual/family, and service dimensions; the answer flow asks for clarification or abstains when these differ or are unclear. Broader coverage answers quote one traceable source row and ask for clarification when matching rows differ.

Every factual answer cites the plan and source document section, adding page when available. The initial implementation has no LLM call. If Gemini is added later, the evidence gate precedes it, citations must resolve to records supplied to the phrasing step, and a post-generation check rejects unsupported claims or returns abstention.

## Interface and diagnostics

The signed-in frontend provides Plans, Chat (the default home page), Profile, admin benefit review, retrieval playground, and evaluation pages. For admins, Plans also contains document upload, processing status, and inspection; members see the plan list only. The Firebase custom claim controls navigation visibility only; protected API routes enforce admin access. Profile edits and account deletion remain placeholders.

The chat page has a roomy transcript, composer, starter prompts, and a new-chat action. Displayed turns are held in frontend memory for the active page session only and clear on new chat, sign-out, reload, or page close. Live message text is not saved to Neon, local storage, session storage, or the evaluation manifest. The browser sends the latest question and resolved plan IDs with a follow-up request; the API validates IDs against currently queryable plans and keeps no conversation state. Evaluation questions remain separately authored test data; persisted evaluation records contain results/metrics without ordinary live query text.

Logical API responses distinguish `answered`, `insufficient_evidence`, and `clarification_needed`, include a concise answer when supported, and carry citations. The API exposes `GET /api/health`, protected `GET /api/plans` and `POST /api/chat`, and admin-only `POST /api/admin/answer/preview` and `GET /api/admin/answer-health`. Preview accepts an explicit retrieval method and chunk strategy for broader coverage answers; numeric answers use supported structured records. The frontend uses Firebase email/password sign-in and sends an ID token as a bearer token. FastAPI verifies the token server-side and fails closed when Firebase credentials are not configured.

All authenticated users see basic diagnostics: resolved plan names, answer/abstention status, cited sources, and a concise indication of the evidence path (structured lookup or retrieval). The admin-only evaluation playground exposes selectable BM25/vector and fixed-size/semantic-section-aware configurations. Admins also see ranked retrieved chunks, scores, processing stages, warnings, parse/extraction/review status, embedding/index versions, and evidence-gate details. Never expose credentials, tokens, privileged configuration, or raw internal stack traces.

## Evaluation and open implementation checks

Maintain 20–30 questions with verified answers and supporting source locations. Measure all four BM25/vector × fixed-size/semantic-section-aware combinations independently by question type, plus extraction accuracy against manual verification, answer accuracy, and latency. Token usage is deferred until optional Gemini phrasing is enabled. Live chat transcripts exist in frontend memory only and are not retained after the active page session; evaluation manifest questions are separately authored test data and live queries are never added to that manifest. Document actual results and limitations in README; do not invent baselines.

Before treating final SBC acceptance as met, verify six publicly available standardized medical SBCs with HMO/PPO/HDHP coverage. For the provisional corpus, validate actual document identities and retain unverified SBC/public-source labels. Also verify the deployed API can run automatic ingestion and build/refresh its in-memory FAISS index within Render's memory limit; Neon storage fits PDFs plus derived data; Render/Firebase/Neon no-card plans remain available to the account; and upload-to-ready-to-answer works end to end.

The qualifying public-SBC corpus is an open final-acceptance prerequisite. Development and provisional evaluation use the six received files and do not depend on resolving that prerequisite first. Remaining implementation settings (API routes, table schema, chunk sizes, retrieval top-k, evidence thresholds, upload byte limit, and model/version measurements) should be set during implementation/evaluation and recorded without weakening provenance or abstention requirements.
