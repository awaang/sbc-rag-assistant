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

- Use the six PDFs currently supplied in `data/source-documents/received/` as the provisional development corpus for ingestion, retrieval, answer-flow, and evaluation work. They remain unverified documents; do not represent them as verified SBCs or public-source documents.
- Preserve each supplied file's actual document type and coverage type. The current set includes medical plan/benefit summaries and dental and vision summaries, so results are provisional and apply only to this mixed set.
- Final qualification as exactly six publicly available standardized medical SBCs, including HMO/PPO/HDHP coverage, is **TBD**. The current six do not satisfy that acceptance criterion unless individually verified or replaced. This does not block development or provisional evaluation on the supplied set.
- Answer questions about plan benefits and costs, including single-plan lookups and comparisons across plans.
- Ground answers in the source documents and cite the source plan and section for every answer.
- Avoid guessing: report low confidence or insufficient source support instead of returning an unsupported answer.
- Compare two retrieval methods: BM25 keyword retrieval and semantic retrieval using locally generated sentence-transformer embeddings searched with FAISS.
- Generate document and query embeddings locally with sentence-transformers; use FAISS for semantic search, with no embedding API. Persist approved document embedding values as ordinary records in Neon so the deployed API can build its in-memory FAISS index. Neon remains the durable relational store; pgvector is not used in the initial implementation.
- Compare fixed-size chunking with semantic/section-aware chunking; evaluate both retrieval methods on both chunk sets using the same labeled questions.
- Provide an admin-only evaluation playground where admins can select a retrieval method and chunking strategy. Ordinary question-answer mode uses the configuration selected from measured results.
- Extract key numerical benefit details into a structured per-plan schema to support reliable lookups and comparisons.
- Evaluate the system with approximately 20–30 questions with known correct answers, measuring answer accuracy and latency per query. Token usage is deferred until the optional Gemini phrasing phase is enabled; deterministic answers have no model-token usage to report.
- Document implementation decisions, chunking tradeoffs, retrieval results, extraction accuracy, and what would change with a real budget.
- **Initial implementation:** use deterministic answer formatting for verified facts, comparisons, citations, clarification, and abstention. Do not integrate or call Gemini in the initial implementation.
- **Later phase:** Gemini may be added only after the deterministic evidence-grounded answer path is implemented and evaluated, and only as an optional final phrasing step over already validated evidence. It must not select facts, fill gaps, alter citations, or override abstention. Its availability/free-tier status is not a prerequisite for the initial demo.
- Provide actual admin PDF uploads and review controls. Uploads are stored durably; a local admin ingestion command processes them and results remain unavailable to answers until reviewed and approved.
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
   - Keep SBC status and public availability explicitly unverified unless confirmed from document evidence and an authoritative public source. Filenames alone do not establish eligibility. Final acceptance as exactly six public medical SBC PDFs spanning HMO, PPO, and HDHP remains **TBD**.
   - Parse the provisional source documents with attention to table structure; evaluate PDF parsing approaches such as pdfplumber or Camelot.
   - Preserve benefit rows and their context during chunking; a table row must not be split across chunks.
   - Explore fixed-size and semantic chunking and document the selected strategy and its tradeoffs.

2. **Retrieval**
   - Provide keyword retrieval using BM25.
   - Provide semantic retrieval using locally generated sentence-transformer embeddings and FAISS vector search, with no embedding API.
   - Compare both methods on the evaluation questions and report which question types each handles better and why.
- Evaluate all four combinations of the two retrieval methods and two chunking strategies against the same questions.
  - BM25 and semantic retrieval must be independently measurable. Which method the demo uses at runtime, and whether retrieval fusion is needed, are **TBD** until evaluation results are available.

3. **Structured benefit extraction**
   - Extract key numerical benefit details from the provisional source documents into a clean schema organized by plan. The initial fields are deductible, emergency room cost sharing, copays, and out-of-pocket maximum; additional coverage is **TBD**.
   - Store each extracted value with its plan identity and source document, page, and section when available.
   - Use structured extracted data for numerical questions such as deductibles, copays, and out-of-pocket maximums, rather than relying on semantic retrieval alone.
   - Record extraction accuracy against verified values in the evaluation set.
   - Exact schema fields and extraction coverage beyond the example benefit types are **TBD**.

4. **Question answering and citations**
   - Accept natural-language questions about a plan or comparisons across plans.
   - Initial implementation produces answers from retrieved evidence and structured extracted data using deterministic formatting; Gemini is excluded from this phase.
   - In a later phase, Gemini may optionally phrase an already validated answer. The evidence gate, facts, citations, and abstention decision remain application-controlled.
   - Cite the source plan and relevant SBC section in every answer; include the page when available.
   - When confidence is low or supporting evidence is missing, say that the answer cannot be established from the available documents instead of guessing.
   - The initial abstention rule is evidence-based: do not provide a requested value if the structured record or retrieved source does not support it with a traceable citation. Numeric confidence thresholds are **TBD** pending evaluation.

5. **Evaluation and documentation**
   - Maintain an evaluation set of approximately 20–30 questions with correct answers.
   - Measure answer/retrieval accuracy and latency per query, and compare BM25 with semantic retrieval. Measure token usage only if optional Gemini phrasing is enabled later.
   - Document chunking choice, retrieval results, extraction accuracy, and lessons for operating with a real budget in the repository README.
   - Evaluation metric definitions and target thresholds are **TBD**.

6. **Authentication**
   - Require authentication before users can submit questions or view answers.
   - The application server must validate authentication on every protected request; frontend-only checks do not satisfy this requirement.
   - Use Firebase Authentication; enforce roles and access on the server. Assign initial admin claims using a privileged local bootstrap operation, not a public self-promotion route.

7. **User interface**
   - Provide a simple interface for authentication, question submission, answers or abstentions, and citations. Visual polish and additional UI features are out of scope.
   - Present a multi-turn, ChatGPT-style conversation in the chat page. Keep the active conversation transcript in browser memory only; clear it when the user starts a new chat, signs out, or reloads/closes the page. Do not persist ordinary chat messages to the backend or browser storage.
   - Provide real admin PDF upload, processing status, parsed evidence/extraction review, and approval controls. The local ingestion command performs PDF parsing and embedding generation to stay within free-host resource limits.
   - Show basic diagnostics to all users and advanced diagnostics only to admins.
   - Provide an admin-only evaluation playground to select BM25 or semantic search and fixed-size or semantic/section-aware chunks. Detailed rank and score traces remain admin-only.

## Non-functional requirements

- **Answer correctness:** Numerical answers must be grounded in the parsed SBC or verified structured extraction; the system must avoid unsupported values.
- **Traceability:** Each answer must let a user identify its source plan and SBC section.
- **Table fidelity:** Parsing and chunking must preserve table rows and the context needed to interpret benefit values.
- **Local retrieval:** Semantic embeddings must be generated locally without requiring an embedding API.
- **Evaluation visibility:** Retrieval quality, answer accuracy, extraction accuracy, and latency must be measurable on the evaluation set. Token usage is measured only if optional Gemini phrasing is enabled. Numeric pass thresholds are **TBD**; report baseline measurements.
- **Performance targets:** Acceptable latency thresholds are **TBD**.
- **Security:** Authentication and admin roles are enforced server-side; privileged Firebase credentials never enter browser code or source control.
- **Deployment:** Run locally and deploy on no-card free tiers. Free-tier sleep/cold starts, quotas, and provider availability are acceptable demo limitations; uninterrupted availability is not promised.
- **Privacy/query retention:** The UI may hold ordinary user messages and answers in browser memory for the active conversation only; clear them on new chat, sign-out, reload, or page close. Do not persist live chat messages to the backend, local storage, session storage, or the evaluation manifest. The versioned 20–30-question evaluation manifest may retain its authored questions and expected answers/evidence as test data. Store aggregate evaluation metrics and per-run identifiers/results without ordinary user query text.

## Acceptance criteria

- [ ] The provisional workflow uses the six received PDFs without misrepresenting their SBC status, public availability, or medical/dental/vision coverage types.
- [ ] Final corpus qualification is resolved: exactly six publicly available standardized medical SBC PDFs, including HMO, PPO, and HDHP plans, or a documented approved change to that target.
- [ ] Provisional source documents are parsed with table structure considered, and chunks do not split table rows.
- [ ] BM25 and local semantic retrieval are both implemented and evaluated against approximately 20–30 questions with known answers.
- [ ] Semantic embeddings are generated locally and searched with FAISS; no hosted embedding API or pgvector vector index is required for the initial implementation.
- [ ] Evaluation results describe which retrieval method performs better for which question types and why.
- [ ] Fixed-size and semantic/section-aware chunking are each evaluated with both retrieval methods, and an admin-only evaluation playground lets admins compare the configurations.
- [ ] Deductible, ER cost sharing, copay, and out-of-pocket maximum values are extracted into a per-plan structured representation with traceable source references, and extraction accuracy is measured against verified values.
- [ ] The tool can answer supported single-plan and cross-plan questions, including numerical benefit questions.
- [ ] The chat UI shows a multi-turn conversation during the active page session and clears the transcript on new chat, sign-out, and reload; ordinary messages are not persisted.
- [ ] Every generated answer cites its source plan and SBC section, with page when available.
- [ ] For low-confidence or unsupported questions, the tool reports insufficient evidence rather than guessing.
- [ ] Per-query accuracy and latency are measured. Token usage is measured only if optional Gemini phrasing is enabled.
- [ ] Initial answer flow is complete and evaluated without Gemini; any later Gemini integration is a separate phase and cannot weaken evidence, citation, or abstention behavior.
- [ ] The README explains chunking decisions, BM25 versus semantic retrieval results, extraction accuracy, and what would be done differently with a real budget.
- [ ] Unauthenticated requests are rejected by the application server; authenticated users can access the question-answering flow.
- [ ] Admin uploads are durable; local ingestion, review, and approval gating work end to end, and non-admin users cannot invoke admin operations.
- [ ] Basic diagnostics are available to all users and advanced diagnostics only to admins.
- [ ] The application runs locally and is deployed on no-card free tiers with cold-start/quota limitations documented.
