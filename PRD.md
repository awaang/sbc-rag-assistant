# Product Requirements Document: SBC Plan Q&A RAG Demo

> **Initialization snapshot:** This is the initial requirements baseline. It defines product constraints, not finalized implementation technology choices; unresolved choices remain **TBD** until evaluated and recorded in `PLAN.md` and `ARCHITECTURE.md`.

## Problem

People comparing health benefit plans need accurate answers to questions about plan costs and coverage, such as deductibles for emergency room visits or out-of-pocket maximums across plans. The relevant information is published in Summary of Benefits and Coverage (SBC) PDFs, but extracting facts reliably is difficult because the documents contain dense, table-heavy content. A wrong or unsupported number undermines trust in the tool.

This project will demonstrate a question-answering tool that reads real, publicly available SBC documents and provides accurate answers grounded in those sources.

## Users

- **People evaluating or comparing health benefit plans** who need to understand plan costs and coverage.
- **Demo users** who ask natural-language questions about the plans represented in the document set.
- **Project evaluators** who need to inspect the retrieval, extraction, and answer quality of the demo.

Users must authenticate before accessing the question-answering application. Authentication is in scope; provider, credential lifecycle, and account model are **TBD**.

## Goals

- Ingest exactly 6 publicly available SBC PDFs, with a mix of HMO, PPO, and HDHP plans, sourced from insurer sites such as Kaiser, Aetna, and Guardian.
- Maintain a distinction between received candidate documents and the verified six-document SBC ingestion corpus; only documents confirmed as SBCs may count toward the corpus requirement. The six currently received PDFs have been inspected and appear to be plan/benefit summaries (including dental and vision summaries), not the standardized SBC form; they do not yet satisfy this requirement.
- Answer questions about plan benefits and costs, including single-plan lookups and comparisons across plans.
- Ground answers in the source documents and cite the source plan and section for every answer.
- Avoid guessing: report low confidence or insufficient source support instead of returning an unsupported answer.
- Compare BM25 keyword retrieval with semantic retrieval using locally generated sentence-transformer embeddings. Vector-index technology and hosting are **TBD**.
- Extract key numerical benefit details into a structured per-plan schema to support reliable lookups and comparisons.
- Evaluate the system with approximately 20–30 questions with known correct answers, measuring answer accuracy, latency, and token usage per query.
- Document implementation decisions, chunking tradeoffs, retrieval results, extraction accuracy, and what would change with a real budget.
- Use the Gemini API only for the final answer-synthesis step, after evidence has been retrieved and checked. The exact model identifier, API key variable name, and request limits are **TBD**; embeddings remain local and do not use Gemini.

## Non-goals

- Providing medical advice or recommendations about which plan a person should choose.
- Covering all insurers, plans, or SBC documents; the initial corpus is limited to the selected 6 public PDFs.
- Treating semantic retrieval alone as the source of truth for numerical benefits.
- Building a production-grade health benefits service. Production deployment, compliance requirements, and service-level commitments are **TBD**.
- A polished user interface is not required for the core demo; a simple question-and-answer interface is sufficient.

## Functional requirements

1. **Document corpus and ingestion**
   - Use exactly 6 verified SBC PDFs, including a mix of HMO, PPO, and HDHP plans.
   - Track received candidate files separately until their document type, plan identity, and SBC status are verified. Filenames alone do not establish corpus eligibility. A missing source URL does not prevent processing a supplied PDF, but public availability must be documented before it counts toward the public-SBC acceptance criterion.
   - Parse SBC content with attention to table structure; evaluate PDF parsing approaches such as pdfplumber or Camelot.
   - Preserve benefit rows and their context during chunking; a table row must not be split across chunks.
   - Explore fixed-size and semantic chunking and document the selected strategy and its tradeoffs.

2. **Retrieval**
   - Provide keyword retrieval using BM25.
   - Provide semantic retrieval using locally generated sentence-transformer embeddings and a vector index. Index technology and hosting are **TBD**.
   - Compare both methods on the evaluation questions and report which question types each handles better and why.
  - BM25 and semantic retrieval must be independently measurable. Which method the demo uses at runtime, and whether retrieval fusion is needed, are **TBD** until evaluation results are available.

3. **Structured benefit extraction**
   - Extract key numerical benefit details from SBCs into a clean schema organized by plan. The initial fields are deductible, emergency room cost sharing, copays, and out-of-pocket maximum; additional coverage is **TBD**.
   - Store each extracted value with its plan identity and source document, page, and section when available.
   - Use structured extracted data for numerical questions such as deductibles, copays, and out-of-pocket maximums, rather than relying on semantic retrieval alone.
   - Record extraction accuracy against verified values in the evaluation set.
   - Exact schema fields and extraction coverage beyond the example benefit types are **TBD**.

4. **Question answering and citations**
   - Accept natural-language questions about a plan or comparisons across plans.
   - Synthesize answers from retrieved evidence and structured extracted data; keep LLM use to the final answer synthesis step.
   - Cite the source plan and relevant SBC section in every answer; include the page when available.
   - When confidence is low or supporting evidence is missing, say that the answer cannot be established from the available documents instead of guessing.
   - The initial abstention rule is evidence-based: do not provide a requested value if the structured record or retrieved source does not support it with a traceable citation. Numeric confidence thresholds are **TBD** pending evaluation.

5. **Evaluation and documentation**
   - Maintain an evaluation set of approximately 20–30 questions with correct answers.
   - Measure accuracy, latency, and token usage per query, and compare BM25 with semantic retrieval.
   - Document chunking choice, retrieval results, extraction accuracy, and lessons for operating with a real budget in the repository README.
   - Evaluation metric definitions and target thresholds are **TBD**.

6. **Authentication**
   - Require authentication before users can submit questions or view answers.
   - The application server must validate authentication on every protected request; frontend-only checks do not satisfy this requirement.
   - Provider, credential lifecycle, and whether users need individual accounts or may share demo access are **TBD**.

7. **User interface**
   - Provide a simple interface for authentication, question submission, answers or abstentions, and citations. Visual polish and additional UI features are out of scope.

## Non-functional requirements

- **Answer correctness:** Numerical answers must be grounded in the parsed SBC or verified structured extraction; the system must avoid unsupported values.
- **Traceability:** Each answer must let a user identify its source plan and SBC section.
- **Table fidelity:** Parsing and chunking must preserve table rows and the context needed to interpret benefit values.
- **Local retrieval:** Semantic embeddings must be generated locally without requiring an embedding API.
- **Evaluation visibility:** Retrieval quality, answer accuracy, extraction accuracy, latency, and token usage must be measurable on the evaluation set. Numeric pass thresholds are **TBD**; report baseline measurements.
- **Performance targets:** Acceptable latency thresholds are **TBD**.
- **Security:** Authentication is required and enforced server-side. Credential storage, session duration, and account recovery policy are **TBD**.
- **Privacy, availability, and deployment requirements:** **TBD**; user-query retention and hosting environment have not been specified.

## Acceptance criteria

- [ ] The corpus contains exactly 6 publicly available SBC PDFs and includes HMO, PPO, and HDHP plans.
- [ ] SBCs are parsed with table structure considered, and chunks do not split table rows.
- [ ] BM25 and local semantic retrieval are both implemented and evaluated against approximately 20–30 questions with known answers.
- [ ] Evaluation results describe which retrieval method performs better for which question types and why.
- [ ] Deductible, ER cost sharing, copay, and out-of-pocket maximum values are extracted into a per-plan structured representation with traceable source references, and extraction accuracy is measured against verified values.
- [ ] The tool can answer supported single-plan and cross-plan questions, including numerical benefit questions.
- [ ] Every generated answer cites its source plan and SBC section, with page when available.
- [ ] For low-confidence or unsupported questions, the tool reports insufficient evidence rather than guessing.
- [ ] Per-query accuracy, latency, and token usage are measured or recorded as applicable to the final synthesis approach.
- [ ] The README explains chunking decisions, BM25 versus semantic retrieval results, extraction accuracy, and what would be done differently with a real budget.
- [ ] Unauthenticated requests are rejected by the application server; authenticated users can access the question-answering flow.
- [ ] Authentication provider/account model, citation presentation details, and latency targets are documented before they are treated as fixed requirements.
