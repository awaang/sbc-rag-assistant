# SBC RAG Assistant

An authenticated demo for answering questions about health benefit plans from real Summary of Benefits and Coverage (SBC) documents. Correctness, citations, table fidelity, and abstention when evidence is insufficient are core requirements.

## Project documents

- [PRD.md](PRD.md) — product goals, requirements, and acceptance criteria.
- [PLAN.md](PLAN.md) — selected stack, implementation milestones, and status.
- [ARCHITECTURE.md](ARCHITECTURE.md) — system components, data flow, and design decisions.
- [AGENTS.md](AGENTS.md) — repository guidance for coding agents.

## Current status and corpus

This repository is in the planning stage. It contains project documentation and six received candidate PDFs under [`data/source-documents/received/`](data/source-documents/received/); application code, ingestion tooling, runtime configuration, evaluation data, and tests have not yet been added.

The received PDFs appear to be plan or benefit summaries, including dental and vision summaries, rather than qualifying standardized medical SBC forms. They do not yet meet the requirement for exactly six public SBCs. No HDHP SBC has been identified. Selecting the qualifying corpus is required for final acceptance and representative evaluation, but does not block building the skeleton and pipeline with labeled candidates or fixtures. See [ARCHITECTURE.md](ARCHITECTURE.md) for inventory and qualification notes. Do not count a candidate toward the corpus until its document type, plan identity, and public source are verified.

## Selected technology direction

- Python 3.11, FastAPI, React, TypeScript, and shadcn/ui.
- Firebase Authentication for sign-in and admin roles; the FastAPI server will verify tokens and enforce permissions.
- Neon Postgres for durable document metadata, uploaded PDF bytes, parsed content, extracted benefit records, citations, and evaluation records.
- pdfplumber for initial PDF extraction, with Camelot added selectively if inspection shows a table needs it.
- BM25 plus FAISS semantic search. The local ingestion CLI generates document embeddings; the API generates query embeddings with the same sentence-transformer model and searches an in-memory FAISS index. Store approved embedding values and model/chunk IDs in Neon so the API can build or refresh its index after restarts and approvals. No embedding API or pgvector index is needed initially. Verify the deployed API's model/index memory and startup requirements.
- Evaluate four combinations: BM25 or semantic vector retrieval, each over fixed-size or semantic/section-aware table-safe chunks. The authenticated evaluation playground will let users compare configurations; ordinary answer mode uses the measured default.
- Initial answers use deterministic formatting for verified facts, comparisons, citations, clarification, and abstention; Gemini is not part of the initial implementation. It may be added later as an optional final phrasing step over validated evidence and cannot supply facts or override abstention.
- Render Free for the React static site and FastAPI web service. The service may sleep when idle, so the first request can be delayed. Persist application data in Neon, not Render's ephemeral filesystem.

These selections target a free, no-credit-card demo within provider limits. Free tiers can sleep, pause, change limits, or require account verification; always confirm current terms before deployment. Admin PDF upload will be real. To fit free-host resource limits, the initial design stores uploads in Neon and uses a local authenticated/administrative ingestion command to parse, extract, embed, and write reviewed results back to Neon. Uploaded documents remain pending until extraction and provenance have been reviewed.

For six SBCs of roughly 2–5 pages each, Neon Free's currently listed 500 MB database allowance is unlikely to be a problem: the corpus is only about 12–30 pages, and the parsed text, metadata, and 384-dimensional embeddings for a modest number of chunks are small compared with that allowance. Original PDF sizes are not known yet, especially whether any charts are embedded as large images, so record actual file sizes before upload and monitor database usage. Neon also has a separate compute-hour quota; a low-volume demo with local ingestion is expected to use little database compute, but this should be checked against actual activity rather than promised in advance. These quotas and tiers can change.

## Planned capabilities

- Ingest exactly six verified public SBCs with table rows, document identity, plan metadata, sections, pages, and source provenance preserved.
- Compare fixed-size and section-aware, row-preserving chunking.
- Independently evaluate BM25 and semantic retrieval using 20–30 labeled questions.
- Extract deductible, ER cost-sharing, copay, and out-of-pocket maximum values into auditable structured records.
- Answer supported questions with citations; clarify ambiguous plan names and abstain when evidence is missing, conflicting, or unverified.
- Show basic answer diagnostics to all users and detailed retrieval, parsing, extraction, and ingestion diagnostics to admins.
- Measure retrieval and answer accuracy, extraction accuracy, latency, and token use when a model is used.

The initial implementation compares BM25 with one semantic retrieval method: sentence-transformer embeddings generated locally and searched by FAISS. Neon remains the cloud relational database for durable app records and uploads, and stores embedding values as ordinary records; it does not perform vector search. The deployed API loads approved embeddings into an in-memory FAISS index and rebuilds it after restarts or corpus approval changes. Chroma or pgvector would be alternative vector-search implementations, not additional retrieval methods, and are out of scope unless evaluation or a concrete deployment constraint justifies changing the design.

## Documentation expectations

As implementation proceeds, update this README with setup and run instructions, actual parser and chunking decisions, measured BM25 versus semantic results, extraction accuracy, limitations, and what additional budget would change. Do not report evaluation results until they have been measured against verified SBCs.
