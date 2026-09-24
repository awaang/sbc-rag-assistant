# SBC RAG Assistant

> **Initialization snapshot:** This repository is at its initial documentation and candidate-document stage. No application has been implemented, and technology choices are provisional/TBD rather than finalized.

An authenticated demo for answering questions about health plan benefits using source documents, traceable evidence, and abstention when evidence is insufficient.

## Project documents

- [PRD.md](PRD.md) — goals, requirements, and acceptance criteria.
- [PLAN.md](PLAN.md) — implementation milestones and status.
- [ARCHITECTURE.md](ARCHITECTURE.md) — system components, data flow, and TBD decisions.
- [AGENTS.md](AGENTS.md) — repository guidance for coding agents.

## Source documents

The six PDFs supplied with the project prompt are stored under [`data/source-documents/received/`](data/source-documents/received/). They have been inspected and appear to be plan/benefit summaries rather than standardized SBC forms: two Aetna medical plan summaries, two Kaiser/Group Health benefit summaries, and Guardian dental and vision benefit summaries. None is currently verified as eligible for the intended medical SBC corpus, and no HDHP SBC has been identified among them.

The project requirements call for exactly six public SBC PDFs. A source URL is not needed to parse or process a supplied PDF: use its filename/document ID and retain section/page provenance. However, public availability must be verified before counting a document toward the public-SBC requirement. Do not treat these received files as the qualifying corpus unless the project scope is deliberately revised.

## Current implementation status

This repository currently contains project documentation and received candidate documents. Application code, ingestion tooling, evaluation data, and runtime setup are not yet established. Setup and run instructions will be added as implementation is built.

## Contributor onboarding

Before making changes, read `AGENTS.md`, then `PRD.md`, `PLAN.md`, `ARCHITECTURE.md`, and this README. Check the current tree and git status first. The initial setup has no install or run commands because no application/runtime has been selected or implemented yet. Keep project changes aligned with the PRD, preserve candidate-vs-verified corpus status, and update the plan and documentation as milestones land.
