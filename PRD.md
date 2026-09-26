# Product Requirements Document: SBC Plan Q&A RAG Demo

This PRD records the agreed project requirements and technology constraints. The selected stack is recorded in `PLAN.md` and `ARCHITECTURE.md`; evaluation-dependent settings remain open until measured.

## Problem

People comparing health benefit plans need accurate answers to questions about plan costs and coverage, such as deductibles for emergency room visits or out-of-pocket maximums across plans. The relevant information is published in Summary of Benefits and Coverage (SBC) PDFs, but extracting facts reliably is difficult because the documents contain dense, table-heavy content. A wrong or unsupported number undermines trust in the tool.

This project will demonstrate a question-answering tool that reads real, publicly available SBC documents and provides accurate answers grounded in those sources.

## Users

- **People evaluating or comparing health benefit plans** who need to understand plan costs and coverage.
- **Demo users** who ask natural-language questions about the plans represented in the document set.
- **Project evaluators** who need to inspect the retrieval, extraction, and answer quality of the demo.

Users must authenticate before accessing the question-answering application. Firebase Authentication is selected for the demo; admin permissions are enforced server-side through Firebase custom claims verified by the application server.

## Goals

- Use the six PDFs currently supplied in `data/source-documents/received/` as the SBC corpus for ingestion, retrieval, answer-flow, and evaluation work. They are treated as verified SBCs (decision recorded 2026-09-25).
- Preserve each supplied file's actual document type and coverage type. The current set includes medical plan/benefit summaries and dental and vision summaries, so results apply to this mixed set.
- Answer questions about plan benefits and costs, including single-plan lookups and comparisons across plans.
- Ground answers in the source documents and cite the source plan and section for every answer.
- Avoid guessing: report low confidence or insufficient source support instead of returning an unsupported answer.
- Compare two retrieval methods: BM25 keyword retrieval and semantic retrieval using locally generated sentence-transformer embeddings searched with FAISS.
- Generate document and query embeddings locally with sentence-transformers; use FAISS for semantic search, with no embedding API. Persist approved document embedding values as ordinary records in Neon so the deployed API can build its in-memory FAISS index. Neon remains the durable relational store; pgvector is not used in the initial implementation.
- Compare fixed-size chunking with semantic/section-aware chunking; evaluate both retrieval methods on both chunk sets using the same labeled questions.
- Provide an admin-only evaluation playground where admins can select a retrieval method and chunking strategy. Ordinary question-answer mode uses the configuration selected from measured results.
- Extract key numerical benefit details into a structured per-plan schema to support reliable lookups and comparisons.
- Evaluate the system with approximately 20–30 questions with known correct answers, measuring answer accuracy, latency, and Gemini token usage per query. Deterministic fallback answers have no model-token usage to report.
- Document implementation decisions, chunking tradeoffs, retrieval results, extraction accuracy, and what would change with a real budget.
- **Deterministic answer path:** use deterministic answer formatting for supported facts, comparisons, citations, clarification, and abstention. This path decides every answer and is the fallback response.
- **Required Gemini response phase (thin, per the original project spec):** Gemini runs only at the very end, after the evidence gate, and only for answers built from retrieved source rows. A rules-based check skips Gemini when the structured benefit data already answers the question and for clarification and insufficient-evidence replies; those return the deterministic text. This overrides the earlier requirement that Gemini write every reply (changed 2026-09-25). The server decides the reply type, facts, and citations; Gemini must not select facts, fill gaps, alter citations, or override abstention. The deterministic answer is returned when Gemini is unconfigured or the API call fails, or when the reply contains a number absent from the evidence, omits a checked value, or drops a checked coverage qualification. Quality, latency, and token usage per query are measured by `python -m app.evaluate --gemini`.
- Provide actual admin PDF uploads and review controls. Uploads are stored durably and automatically trigger parsing, chunking, benefit extraction, embedding, and readiness assessment in the FastAPI service. Interrupted queued work resumes after a service restart; repeated interruptions stop with a visible failure and an admin Retry action. The local pipeline command remains available for maintenance. Routine queryability does not require document approval or per-benefit confirmation.
- Target a fully free, no-credit-card local/deployed demo using Firebase Spark, Neon Free, and Render Free, subject to current provider limits and account verification. Free-tier cold starts and quotas are acceptable limitations and must be documented.
- Show basic evidence-path/citation diagnostics to all users and detailed retrieval, parsing, extraction, and ingestion diagnostics to admins.

## Non-goals

- Providing medical advice or recommendations about which plan a person should choose.
- Covering all insurers, plans, or benefit documents; provisional development is limited to the six received PDFs, with final public-SBC corpus qualification still TBD.
- Treating semantic retrieval alone as the source of truth for numerical benefits.
- Building a production-grade health benefits service. Production deployment, compliance requirements, and service-level commitments are **TBD**.
- A polished user interface is not required for the core demo; a simple question-and-answer interface is sufficient.

## Functional requirements

1. **Document corpus and ingestion**
   - Use the six supplied PDFs as the current provisional development corpus and track their document identity, type, coverage type, and provenance accurately.
   - Parse the provisional source documents with attention to table structure; evaluate PDF parsing approaches such as pdfplumber or Camelot.
   - Preserve benefit rows and their context during chunking; a table row must not be split across chunks.
   - Explore fixed-size and semantic chunking and document the selected strategy and its tradeoffs.
   - Record parsing, chunking, benefit extraction, and embedding stages. `ready` and `ready_with_warnings` require all stages to complete and enough current embeddings for retrieval. Processing, incomplete, and critically failed documents remain unavailable. Preserve previously approved documents as queryable.
   - Treat an authenticated admin upload as already reviewed by that admin. After successful processing, approve it automatically for questions, with warnings retained. No document verification click is required. This approval does not establish SBC status or public availability.
   - Treat an isolated page parse failure, one ambiguous benefit, or a table extraction failure as a warning when other usable evidence remains. An unreadable PDF, essentially no usable text, unknown plan identity, processing crash, or insufficient embeddings is critical. A completed command alone does not establish readiness.

2. **Retrieval**
   - Provide keyword retrieval using BM25.
   - Provide semantic retrieval using locally generated sentence-transformer embeddings and FAISS vector search, with no embedding API.
   - Compare both methods on the evaluation questions and report which question types each handles better and why.
- Evaluate all four combinations of the two retrieval methods and two chunking strategies against the same questions.
  - BM25 and semantic retrieval must be independently measurable. Hybrid reciprocal-rank fusion is implemented and measured as a third method. Ordinary chat uses BM25 with section-aware chunks; changing the runtime method remains **TBD** pending a user decision on the measured results.

3. **Structured benefit extraction**
   - Extract key numerical benefit details from the provisional source documents into a clean schema organized by plan. The initial fields are deductible, emergency room cost sharing, copays, and out-of-pocket maximum; additional coverage is **TBD**.
   - Store each extracted value with its plan identity and source document, page, and section when available.
   - Use structured extracted data for numerical questions such as deductibles, copays, and out-of-pocket maximums, rather than relying on semantic retrieval alone.
   - For compound questions whose requested facts span rows, the deterministic answer path may select multiple BM25-retrieved, provenance-bearing source rows and adjacent qualifiers. It must require every requested part, preserve table column context, and abstain when any part lacks traceable support. This source path complements structured extraction; it does not turn semantic similarity into evidence for a numerical value.
   - Allow unambiguous automatically extracted candidates to support numerical answers when value, requested context, page, and detected section are usable. Optional admin correction and explicit verification remain available.
   - Record extraction accuracy against verified values in the evaluation set.
   - Exact schema fields and extraction coverage beyond the example benefit types are **TBD**.

4. **Question answering and citations**
   - Accept natural-language questions about a plan or comparisons across plans.
   - Produce answers from retrieved evidence and structured extracted data using deterministic formatting.
   - Gemini writes the final reply for retrieved-source answers only; a rules-based check skips it for structured-benefit answers and non-answers. The evidence gate, facts, citations, and abstention decision remain application-controlled, and the deterministic answer is returned if Gemini fails or its reply fails the evidence check.
   - Cite the source plan and relevant document section in every answer; include the page when available.
   - When confidence is low or supporting evidence is missing, say that the answer cannot be established from the available documents instead of guessing.
   - The initial abstention rule is evidence-based: do not provide a requested value if the structured record or retrieved source does not support it with a traceable citation. Numeric confidence thresholds are **TBD** pending evaluation.
   - A warning affecting one part of a document must not suppress independent supported answers. Clarify or abstain when the requested value depends on missing, ambiguous, conflicting, or untraceable evidence.

5. **Evaluation and documentation**
   - Maintain an evaluation set of approximately 20–30 questions with correct answers.
   - Measure answer/retrieval accuracy and latency per query, and compare BM25 with semantic retrieval. Measure Gemini token usage and latency, and compare Gemini-phrased answers with deterministic output.
   - Document chunking choice, retrieval results, extraction accuracy, and lessons for operating with a real budget in the repository README.
   - Evaluation metric definitions and target thresholds are **TBD**.

6. **Authentication**
   - Require authentication before users can submit questions or view answers.
   - The application server must validate authentication on every protected request; frontend-only checks do not satisfy this requirement.
   - Use Firebase Authentication; enforce roles and access on the server. Assign initial admin claims using a privileged local bootstrap operation, not a public self-promotion route.

7. **User interface**
   - Provide a simple interface for authentication, question submission, answers or abstentions, and citations. Visual polish and additional UI features are out of scope.
   - Present a multi-turn, ChatGPT-style conversation in the chat page. Keep the active conversation transcript in browser memory only; clear it when the user starts a new chat, signs out, or reloads/closes the page. Do not persist ordinary chat messages to the backend or browser storage.
   - Provide real admin PDF upload, automatic processing and approval, per-stage status and warnings, and parsed evidence/extraction inspection. The FastAPI service runs parsing and embedding after upload; local maintenance commands use the same pipeline.
   - Show basic diagnostics to all users and advanced diagnostics only to admins.
   - Provide an admin-only evaluation playground to select BM25 or semantic search and fixed-size or semantic/section-aware chunks. Detailed rank and score traces remain admin-only.

## Non-functional requirements

- **Answer correctness:** Numerical answers must be grounded in unambiguous, cited source extraction or explicit verification; the system must avoid unsupported values.
- **Traceability:** Each answer must let a user identify its source plan and document section.
- **Table fidelity:** Parsing and chunking must preserve table rows and the context needed to interpret benefit values.
- **Local retrieval:** Semantic embeddings must be generated locally without requiring an embedding API.
- **Evaluation visibility:** Retrieval quality, answer accuracy, extraction accuracy, latency, and Gemini token usage must be measurable on the evaluation set. Numeric pass thresholds are **TBD**; report baseline measurements.
- **Performance targets:** Acceptable latency thresholds are **TBD**.
- **Security:** Authentication and admin roles are enforced server-side; privileged Firebase credentials never enter browser code or source control.
- **Deployment:** Run locally and deploy on no-card free tiers. Free-tier sleep/cold starts, quotas, and provider availability are acceptable demo limitations; uninterrupted availability is not promised.
- **Privacy/query retention:** The UI may hold ordinary user messages and answers in browser memory for the active conversation only; clear them on new chat, sign-out, reload, or page close. Do not persist live chat messages to the backend, local storage, session storage, or the evaluation manifest. The versioned 20–30-question evaluation manifest may retain its authored questions and expected answers/evidence as test data. Store aggregate evaluation metrics and per-run identifiers/results without ordinary user query text.

## Acceptance criteria

- [x] The workflow uses the six received SBC PDFs without misrepresenting their medical/dental/vision coverage types.
- [ ] Final corpus qualification is resolved: exactly six publicly available standardized medical SBC PDFs, including HMO, PPO, and HDHP plans, or a documented approved change to that target.
- [ ] Provisional source documents are parsed with table structure considered, and chunks do not split table rows.
- [ ] BM25 and local semantic retrieval are both implemented and evaluated against approximately 20–30 questions with known answers.
- [ ] Semantic embeddings are generated locally and searched with FAISS; no hosted embedding API or pgvector vector index is required for the initial implementation.
- [ ] Evaluation results describe which retrieval method performs better for which question types and why.
- [ ] Fixed-size and semantic/section-aware chunking are each evaluated with both retrieval methods, and an admin-only evaluation playground lets admins compare the configurations.
- [ ] Deductible, ER cost sharing, copay, and out-of-pocket maximum values are extracted into a per-plan structured representation with traceable source references, and extraction accuracy is measured against verified values.
- [ ] The tool can answer supported single-plan and cross-plan questions, including numerical benefit questions.
- [ ] The chat UI shows a multi-turn conversation during the active page session and clears the transcript on new chat, sign-out, and reload; ordinary messages are not persisted.
- [ ] Every generated answer cites its source plan and document section, with page when available.
- [ ] For low-confidence or unsupported questions, the tool reports insufficient evidence rather than guessing.
- [ ] Per-query accuracy, latency, and Gemini token usage are measured.
- [ ] The deterministic answer flow is complete and evaluated on its own, and serves as the fallback.
- [ ] Gemini writes retrieved-source replies in the demo (skipped by rule otherwise), cannot weaken evidence, citation, or abstention behavior, and is compared with deterministic output for quality, latency, and token use. Comparative quality claims remain **TBD** until measured.
- [ ] The README explains chunking decisions, BM25 versus semantic retrieval results, extraction accuracy, and what would be done differently with a real budget.
- [ ] Unauthenticated requests are rejected by the application server; authenticated users can access the question-answering flow.
- [ ] Admin uploads are durable and start processing automatically; readiness, warning handling, restart recovery, and Retry work end to end without mandatory approval, and non-admin users cannot invoke admin operations.
- [ ] Basic diagnostics are available to all users and advanced diagnostics only to admins.
- [ ] The application runs locally and is deployed on no-card free tiers with cold-start/quota limitations documented.
