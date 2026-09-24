# Implementation Plan: SBC RAG Demo

> **Initialization snapshot:** This plan records the starting state, not completed implementation. The stack bullets below are provisional planning assumptions; technology selections and hosting decisions remain **TBD** until evaluated and approved. Do not treat listed tools/frameworks as finalized commitments.

This plan tracks implementation of the demo described in `PRD.md` and `ARCHITECTURE.md`. Complete phases in order; keep the app runnable at each milestone and update this checklist as work lands.

## Implementation stack

- Use Python 3.11 for ingestion, retrieval, structured extraction, and backend services.
- Use React with shadcn/ui for the browser interface and an HTTP API between the frontend and application server.
- Start PDF extraction with pdfplumber. Inspect results from all six documents; use a complementary parser for tables that are not extracted adequately.
- Implement BM25 and generate sentence-transformer embeddings locally. Vector-index technology and hosting are **TBD**.
- Store corpus metadata, parsed chunks, extracted benefit records, and semantic vectors in a separate database service. Provider and vector support are **TBD** until selected.
- Use the Gemini API for final answer synthesis behind a replaceable interface, with a deterministic formatting path for verified structured answers.
- Use automated tests for parsing, provenance, extraction, retrieval, authentication, citations, abstention, and end-to-end behavior.
- Read credentials and optional service configuration from environment variables; never commit secrets.

## Ordered implementation phases

### Phase 1 — Corpus and runnable project skeleton

- [x] Receive six candidate plan-summary PDFs and record their provisional filename-based classifications in `ARCHITECTURE.md`; keep them separate from the verified SBC ingestion corpus pending content review.
- [ ] Select and record exactly six verified public SBC PDFs, plan names/types, and available plan-year information; add source URLs when available and confirm HMO, PPO, and HDHP representation. The six supplied candidate PDFs have been inspected and appear to be plan/benefit summaries rather than standardized SBCs; none currently qualifies, and no HDHP SBC has been identified.
- [ ] Add a small Python project layout for application code, ingestion, evaluation data, and tests; document the structure in `AGENTS.md` if it changes materially.
- [ ] Add Python and frontend dependency/configuration files, `.env.example` with names only, and ignore local secrets, downloaded PDFs if needed, generated indexes, and runtime databases.
- [ ] Add a minimal React + shadcn/ui frontend shell and backend health endpoint that run before the RAG features are implemented.
- [ ] Update `README.md` with Python setup, environment setup, corpus acquisition/source notes, and how to run the skeleton.

**Milestone:** A clean checkout can be configured and the empty demo can be started.

### Phase 2 — SBC parsing, provenance, and table-safe chunks

- [ ] Parse all six PDFs page by page; retain plan/document identity, page number, section heading where detectable, and table content.
- [ ] Inspect parser output for all six files and correct/flag extraction failures; add Camelot only for PDFs/tables where pdfplumber output is inadequate.
- [ ] Normalize table rows with their header/context and ensure no row is split across chunks.
- [ ] Implement fixed-size and semantic/section-aware chunking as comparable strategies; preserve chunk IDs and source references.
- [ ] Add parser/chunker fixtures or tests for page provenance, table headers, row integrity, and malformed/unreadable pages.
- [ ] Update `README.md` with parser behavior and observed table limitations; update `ARCHITECTURE.md` if the actual pipeline differs.

**Milestone:** All six SBCs produce inspectable text/table records and traceable, row-preserving chunks.

### Phase 3 — Structured benefit extraction

- [ ] Define typed per-plan records for deductible, ER cost sharing, copays, and out-of-pocket maximum, including source document, section/page, and extraction status.
- [ ] Extract values from parsed tables and keep values exactly as represented (including in-network/out-of-network distinctions and coinsurance wording); missing or ambiguous values remain unverified rather than inferred.
- [ ] Save normalized records in the selected database service and provide a way to inspect/edit verified extractions during development.
- [ ] Manually verify extracted values against each SBC and record extraction accuracy by benefit category and plan.
- [ ] Add tests for currency, percentages, ranges, waived/deductible wording, missing values, and conflicting or ambiguous table cells.
- [ ] Update `README.md` with schema rationale, extraction accuracy, and known limitations.

**Milestone:** Numerical values can be retrieved by plan with auditable SBC provenance.

### Phase 4 — BM25 and semantic retrieval baselines

- [ ] Build BM25 and semantic indexes over the same selected chunks, generating semantic embeddings locally and keeping the vector-index technology configurable until selected.
- [ ] Keep plan/document filters and provenance attached to both retrieval result types.
- [ ] Create 20–30 evaluation questions with verified expected answer, plan(s), evidence location, and question type (for example exact-number lookup, terminology paraphrase, or comparison).
- [ ] Measure retrieval success independently for BM25 and semantic retrieval, using a documented definition such as whether a supporting source appears in the top results.
- [ ] Compare fixed-size and semantic/section-aware chunking on the same evaluation questions; document results and choose a default chunking strategy.
- [ ] Record per-query latency and retrieval scores/results; document where each method wins and why.

**Milestone:** Reproducible baseline results establish the chosen chunking strategy and retrieval behavior.

### Phase 5 — Authenticated answer flow and citations

- [ ] Choose the demo authentication provider/account model and document required environment variables; implement provider-backed authentication or a clearly scoped demo login without hardcoded credentials.
- [ ] Enforce authentication on the server for every question/answer request.
- [ ] Implement plan resolution; ask the user to clarify an ambiguous plan instead of choosing silently.
- [ ] Route numerical questions through verified structured benefit records; use BM25/semantic evidence for coverage questions and as supporting context.
- [ ] Implement an evidence gate: abstain on missing, ambiguous, or conflicting support; do not let the LLM fill in unsupported numbers.
- [ ] Return plan and SBC section citations, adding page when available; validate citations against the evidence supplied to answer generation.
- [ ] Add thin Gemini API synthesis behind an adapter; bypass it for direct structured answers where possible and keep a deterministic no-LLM path. Read the API key from an environment variable and do not commit it.
- [ ] Add tests for unauthenticated rejection, supported single-plan and comparison questions, citations, ambiguous plan names, missing evidence, and conflicting evidence.

**Milestone:** An authenticated user can get a cited answer or a clear abstention, with numeric values grounded in extraction.

### Phase 6 — Demo UI, end-to-end evaluation, and documentation

- [ ] Complete the React + shadcn/ui query flow: login/auth state, question input, answer/abstention status, and visible citations.
- [ ] Run the 20–30-question set end to end; report answer accuracy, extraction accuracy, retrieval results by method/question type, latency, and token usage when an LLM is used.
- [ ] Verify cross-plan comparisons and unsupported questions; correct issues in implementation rather than weakening expected answers/tests.
- [ ] Record limitations and measured baseline results; numeric pass thresholds remain unset unless justified by project goals.
- [ ] Finish `README.md` setup/run instructions, evaluation findings, chunking strategy and results, extraction accuracy, limitations, and what would change with a real budget.
- [ ] Update `ARCHITECTURE.md` and this checklist to match the delivered implementation and mark completed items.

**Milestone:** The demo is reproducible, its behavior is documented, and results can be inspected against verified sources.

## Definition of done

- The demo uses exactly six public SBC PDFs spanning HMO, PPO, and HDHP plans.
- Authentication is checked server-side; no secrets are committed.
- Table-aware parsing and row-preserving chunks retain plan, section, and page provenance when available.
- BM25 and local semantic retrieval are implemented and compared on 20–30 verified questions.
- Numerical benefit extraction is measured against manually verified SBC values.
- Supported answers cite the plan and section (page when available); unsupported, ambiguous, or conflicting questions abstain or request clarification.
- Accuracy, latency, and token usage are measured as applicable, with methods and limitations explained in `README.md`.
