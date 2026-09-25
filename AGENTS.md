# Coding Agent Guidelines

These repository files record current requirements and selected technology decisions. Preserve the PRD and approved stack; update this note when requirements or decisions change.

## Project purpose

Build a demo that answers questions about health benefit plans using the six PDFs currently received as a provisional development corpus. Their SBC status and public availability remain unverified; do not describe them as verified SBCs. Answer correctness, traceable citations, and abstaining when evidence is insufficient are core requirements. Authentication is in scope.

## Read before making changes

1. Read `PRD.md` for product requirements and constraints.
2. Read `PLAN.md` for the implementation plan and current task status. If it does not exist yet, do not invent its contents; note that it is pending and continue to follow the PRD and architecture.
3. Read `ARCHITECTURE.md` for the intended system flow and known open design choices.
4. Read `README.md` for setup and usage instructions.
5. Inspect the relevant existing implementation and tests before modifying code. Follow the repository's established patterns where they exist.

## Project brief alignment

- Treat `PRD.md` as the canonical, durable statement of the project brief. Before adding or changing behavior, check it and `ARCHITECTURE.md`/`PLAN.md` for alignment.
- Do not silently omit or replace a project-brief requirement. If a requirement is ambiguous, conflicts with the current design, or appears infeasible, explain the discrepancy to the user and mark it **TBD** in the relevant planning document until resolved.
- Keep the core constraints visible in implementation: use the six received PDFs as a provisional development corpus while preserving their unverified status; the set includes dental and vision summaries and does not establish HMO/PPO/HDHP SBC coverage; table-preserving parsing/chunking with provenance; BM25 and local sentence-transformer embeddings searched with FAISS; structured benefit extraction; deterministic answer formatting in the initial implementation; Gemini is explicitly deferred to a later phase and must remain an evidence-bound phrasing addition; citations and abstention; Firebase authentication with server-enforced admin roles; real admin upload with automatic parsing/extraction/embedding in the FastAPI service, restart recovery, automatic readiness assessment and approval for successful admin uploads, and optional benefit correction/verification; and 20–30-question evaluation. The local pipeline command remains a maintenance path. Treat performance and evaluation as provisional and corpus-scoped; final SBC/public-source qualification remains TBD.
- Keep the roles distinct: sentence-transformers generates embeddings locally, FAISS performs local vector search, and Neon Postgres stores durable relational application data. Do not duplicate vectors in pgvector unless a later requirement justifies changing the selected vector index.
- Do not substitute hosted embeddings or managed file-search RAG. An LLM is optional and must remain a thin final phrasing step; it may never provide unsupported benefit facts.
- Keep live chat transcripts in frontend memory for the active page session only; clear them on new chat, sign-out, reload, or page close. Do not persist ordinary user messages to Neon, browser storage, or the evaluation manifest.

## Project structure

The repository contains project documentation and environment configuration at its root, a FastAPI backend, a React/Vite frontend, and received candidate PDFs under `data/source-documents/received/`:

- `AGENTS.md` — coding-agent instructions.
- `PRD.md` — product requirements and constraints.
- `PLAN.md` — implementation plan and progress tracking.
- `ARCHITECTURE.md` — architecture, component responsibilities, flows, and unresolved decisions.
- `README.md` — project setup and usage; keep it updated as implementation is added.
- `.env.example` — names of local frontend/backend configuration values; never put secret values here.
- `backend/` — FastAPI API and Python dependency list.
- `backend/migrations/` — ordered PostgreSQL schema migrations; embeddings are ordinary array values, not pgvector.
- `frontend/` — React + TypeScript + Vite UI, Tailwind styling, and shadcn-style components.
- `render.yaml` — Render Blueprint for the static frontend and API service; account-specific secrets stay in Render's environment settings.
- `data/source-documents/received/metadata.json` — provisional metadata for received candidate PDFs; null values are unknown and records do not establish SBC eligibility.

Evaluation artifacts have not been established yet. Backend tests currently live in `backend/tests/` and use the pytest configuration in `backend/pytest.ini`. Inspect the current tree before assuming other paths or creating new structures. Keep the layout small and clear; update this section if major directories are introduced.

## Engineering guidelines

- Keep implementation simple, readable, and aligned with `PRD.md` and `ARCHITECTURE.md`.
- Prefer minimal changes and avoid introducing major frameworks or infrastructure unless required by the project goals.
- Keep codebase documentation factual and technology-neutral where the requirements allow a choice. Do not add technology decision rationales to code comments or the README unless they are needed to explain non-obvious implementation behavior. Explain technology tradeoffs to the user when asked.
- Keep the application runnable after each milestone.
- Do not hardcode secrets or credentials. Read sensitive configuration from environment variables and document required variable names without including secret values.
- Treat SBC-derived numbers as evidence-backed data: preserve their source document and section/page provenance when available, and do not infer missing values.
- Preserve table rows and enough header/context to interpret benefit values when parsing and chunking documents.
- Keep authentication enforcement on the server side; frontend-only checks do not meet the requirement.
- Do not change tests merely to make a failing implementation pass unless the underlying requirement has changed. Update tests only when behavior or requirements intentionally change.
- Do not add features outside the PRD unless they are explicitly marked TBD and then approved or added to the plan.

## Documentation and progress tracking

- Keep `README.md` updated whenever setup instructions or major architecture/usage behavior changes. Document how to use the selected tools, but do not add unsolicited technology-choice advocacy or rationale.
- After completing a significant milestone, update `PLAN.md` with progress and any changed tasks, and update affected setup instructions in `README.md`.
- Keep `ARCHITECTURE.md` aligned with meaningful changes to data flow, components, or interfaces.
- If implementation reveals a conflict or gap in the PRD, architecture, or plan, document the discrepancy and resolve it in project docs rather than silently choosing a different behavior.
