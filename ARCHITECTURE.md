# SBC RAG Assistant Architecture

## Purpose and status

The demo answers questions about health plan costs and coverage from exactly six verified public Summary of Benefits and Coverage (SBC) PDFs. Its core requirements are correctness, traceable citations, table fidelity, and abstention when evidence is insufficient. The repository is currently at the planning/candidate-document stage; no application or ingestion implementation exists yet.

Six supplied candidate PDFs are stored in `data/source-documents/received/`. Based on titles and inspected contents, they appear to be plan or benefit summaries, including dental and vision summaries, rather than standardized medical SBCs. They do not qualify for the active corpus unless the scope is deliberately changed. No HDHP SBC has been identified yet; this is an open corpus gap, not a blocker to beginning implementation, and an HDHP SBC may be added later. Exact corpus membership remains **TBD**.

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
- **Identity and roles:** Firebase Authentication Spark. Users authenticate with email/password or an enabled social provider. The browser sends a Firebase ID token; FastAPI verifies it on every protected call. Admin status is a Firebase custom claim assigned using a local one-time bootstrap tool and is checked server-side for upload, review, and administrative diagnostics.
- **Database:** Neon Postgres Free. Store document/plan metadata, uploaded original PDF bytes for the small demo corpus, parsed pages/table rows/chunks, structured benefits, citations, ingestion state, and evaluation labels/results. Browser code never receives Neon credentials.
- **Keyword retrieval:** BM25 using `rank-bm25`, independently measurable over canonical chunks.
- **Semantic retrieval:** Generate document embeddings with configurable `sentence-transformers/all-MiniLM-L6-v2` in the local ingestion CLI; generate each query embedding in the FastAPI service using the same model version. Persist approved document embeddings with model/version and chunk IDs in Neon as ordinary application data. The API builds an in-memory FAISS index from approved embeddings at startup and refreshes/rebuilds it after approval changes. No embedding API or pgvector index is used in the initial implementation. FAISS result IDs map back to canonical chunks/provenance in Neon. Verify that the deployed API can load the model and index within its memory/startup limits.
- **Vector-backend scope:** The requested comparison is BM25 versus semantic retrieval. Use FAISS as the one semantic search implementation; do not add Chroma or pgvector in parallel unless a later requirement or measured limitation justifies a documented change.
- **Chunking:** Compare fixed-size chunks with semantic/section-aware chunks. Preserve each table row and the header/plan/network context needed to interpret it. Select using labeled retrieval results, not intuition alone.
- **Experiment matrix:** Retrieval method and chunking strategy are separate variables: evaluate BM25 and semantic vector search over each of the two chunk sets (four combinations) using the same question set. Store both chunk sets with a strategy/version key, not separate copies of the source or benefit records.
- **Answers, initial implementation:** Deterministic response formatting for structured numeric facts and comparisons, plus clarification and abstention. Gemini is not integrated or called in this phase.
- **Answers, later optional phase:** Gemini may be added only after the deterministic answer path is implemented and evaluated. It may phrase backend-validated answer content, but cannot select facts, create or alter citations, fill evidence gaps, or override abstention. The application remains usable when Gemini is unavailable or disabled.
- **Deployment:** Render Free hosts the static frontend and FastAPI service. Neon and Firebase provide persistent database and identity services. Render's web service may sleep after inactivity and has an ephemeral filesystem; all durable records and files therefore live outside Render. First request after sleep may take about a minute.
- **No-card cost constraint:** Target only free/no-payment-method plans, no custom domain, no SMS authentication, no paid model/API, and no paid persistent disk. Provider quotas, account verification, availability, and plan terms can change; confirm before deployment. A free tier is not an uptime guarantee.

## Corpus and ingestion flow

### Real admin upload and processing

1. An admin uploads a PDF and descriptive metadata in React.
2. FastAPI verifies the Firebase ID token and admin claim, checks file type/size, and stores the original PDF and upload record in Neon. Status begins as `uploaded`.
3. A local ingestion CLI, run by the project maintainer, fetches pending uploads from Neon. It parses pages and tables, records section/page provenance, normalizes rows, creates row-preserving chunks, extracts candidate benefits, generates document embeddings locally, and writes outputs back to Neon. Embeddings are stored as ordinary per-chunk values with model/version metadata; this does not require pgvector.
4. The ingestion process records issues and moves a document to `needs_review`; extracted benefit records remain unverified.
5. An admin reviews source metadata, parsed evidence, and candidate benefit values in the UI; corrections/approval are recorded. Only approved documents/chunks and verified benefit values enter normal answer retrieval.

This is a genuine upload and ingestion workflow. PDF parsing and document-embedding generation consume the maintainer's local CPU/RAM when the CLI runs. At query time, the deployed FastAPI service embeds the question locally, searches its in-memory FAISS index, and fetches matching approved chunks/provenance from Neon. It loads the sentence-transformer model and approved embeddings on startup, and refreshes the index after approval changes. Render restarts/cold starts therefore reconstruct the index from Neon, without relying on the maintainer's computer. Verify that the model and index fit the selected API service's memory and startup limits. Keep upload size/corpus limits within Neon Free storage/egress quotas. If documents outgrow Neon storage, evaluate a no-card object-storage service before changing the design.

### Parsing, provenance, and data records

For every document retain stable document and plan IDs, insurer, plan name/type/year, verified public source URL, original filename, upload/approval state, and document checksum. Public availability and SBC status must be established before it counts toward the six-SBC requirement.

For parsed pages/rows/chunks retain document/plan IDs, stable record IDs, page, section heading when detectable, table and row context, parse status, and chunk strategy/version. Each table row must stay intact with sufficient headers/context; mark unavailable provenance rather than inventing it.

Structured benefit records store the value exactly as stated, category, plan/document identity, network and individual/family distinctions when present, source section/page/row, reviewer status, and missing/ambiguous/conflicting status. Initial categories are deductible, ER cost sharing, copays, and out-of-pocket maximum. Missing data is never represented as zero.

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

BM25 and FAISS semantic search run independently in evaluation across both chunking strategies. The authenticated evaluation playground lets a user explicitly select a retrieval method and chunking strategy to compare behavior. Detailed rank/score output is admin-only; all users may see selected method/strategy, plan resolution, citations, and answered/abstained status. Ordinary query mode uses the configuration selected from measured results; runtime fusion is not assumed. Numerical comparisons use structured verified records as their source of truth and may use retrieved SBC rows as corroboration. Comparisons must preserve comparable dimensions (e.g. in-network vs out-of-network, individual vs family). If dimensions differ or are unclear, explain the distinction or abstain rather than collapsing values.

Every factual answer cites plan and SBC section, adding page when available. The initial implementation has no LLM call. If Gemini is added later, the evidence gate precedes it, citations must resolve to records supplied to the phrasing step, and a post-generation check rejects unsupported claims or returns abstention.

## Interface and diagnostics

Logical API responses distinguish `answered`, `insufficient_evidence`, and `clarification_needed`, include a concise answer when supported, and carry citations. Concrete routes and wire schema are implementation details to define with the API skeleton.

All authenticated users see basic diagnostics: resolved plan names, answer/abstention status, cited sources, and a concise indication of the evidence path (structured lookup or retrieval). The evaluation playground exposes selectable BM25/vector and fixed-size/semantic-section-aware configurations. Admins additionally see ranked retrieved chunks, scores, parse/extraction/review status, ingestion errors, embedding/index versions, and evidence-gate details. Never expose credentials, tokens, privileged configuration, or raw internal stack traces.

## Evaluation and open implementation checks

Maintain 20–30 questions with verified answers and supporting source locations. Measure all four BM25/vector × fixed-size/semantic-section-aware combinations independently by question type, plus extraction accuracy against manual verification, answer accuracy, latency, and token usage if an LLM is used. Document actual results and limitations in README; do not invent baselines.

Before relying on the design, verify: the six documents are valid public SBCs with HMO/PPO/HDHP coverage; the deployed API can build/refresh its in-memory FAISS index from approved embedding records in Neon; chosen sentence-transformer model size/startup fits local ingestion; Neon storage fits PDFs plus derived data; Render/Firebase/Neon no-card plans remain available to the account; and upload/admin/local-ingestion-to-review flow works end to end.

The qualifying six-document corpus is an open final-acceptance and representative-evaluation prerequisite, but it does not block building the application skeleton or ingestion pipeline with clearly labeled candidates/fixtures. Remaining implementation settings (API routes, table schema, chunk sizes, retrieval top-k, evidence thresholds, upload byte limit, and model/version measurements) should be set during implementation/evaluation and recorded without weakening provenance or abstention requirements.
