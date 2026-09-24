# SBC RAG Assistant Architecture

> **Initialization snapshot:** This is an initial conceptual architecture. It captures required flows and open questions; component and technology choices are not finalized. Items marked **TBD** remain open pending evaluation and explicit documentation.

## Purpose and scope

This architecture describes the demo for answering questions from exactly six publicly available Summary of Benefits and Coverage (SBC) PDFs. It supports authenticated access, table-aware ingestion, BM25 and local semantic retrieval, structured benefit extraction, cited answers, abstention when evidence is insufficient, and evaluation on a labeled question set.

The corpus must include a mix of HMO, PPO, and HDHP plans. Six PDFs supplied with the project prompt are stored in `data/source-documents/received/` and have been inspected. Based on their titles and contents, they appear to be plan/benefit summaries rather than standardized SBC forms; none is currently verified as eligible for the required six-document corpus. Exact corpus membership remains **TBD**; see the candidate inventory below.

### Received source-document inventory

The received filenames and inspected contents indicate the following. These files are not treated as indexed SBC documents because they do not appear to be standardized SBC forms.

| Received file | Filename-indicated type | Corpus status |
|---|---|---|
| `Aetna OAMC Plan Summary  01.01.2017.pdf` | Aetna Open Access Managed Choice POS medical plan summary, effective 2017-01-01 | Inspected; appears to be a plan summary, not a standardized SBC |
| `Aetna HMO Plan Summary 01.01.2017.pdf` | Aetna HMO medical plan summary, effective 2017-01-01 | Inspected; appears to be a plan summary, not a standardized SBC |
| `Kaiser HMO Plan Summary 2017.pdf` | Kaiser Permanente Traditional Plan benefit summary, 2017 | Inspected; explicitly titled Benefit Summary, not a standardized SBC |
| `Kaiser WA.pdf` | Group Health Cooperative Multisite Benefit Summary, effective 2017-01-01 | Inspected; explicitly titled Benefit Summary, not a standardized SBC |
| `Guardian Dental PPO Plan Summary 2017.pdf` | Guardian DentalGuard Preferred PPO dental benefit summary, 2017 | Inspected; dental-only summary, not a medical SBC |
| `Guardian VSP Vision Plan Summary 2017.pdf` | Guardian VSP vision benefit summary, 2017 | Inspected; vision-only summary, not a medical SBC |

These six supplied PDFs can be processed without source URLs. Use the filename and a stable document ID as the source reference, and retain page and section details from the PDF. A source URL is optional for processing and citation, but public availability must be verified separately before a file counts toward the PRD's public-SBC corpus requirement. The received files may be kept as excluded candidates or supplemental examples; do not silently count them as the required six SBCs. No HDHP SBC has been identified in the received set.

## System overview

The system has three flows:

1. **Ingestion:** PDFs are parsed with table structure preserved, section/page and plan metadata are attached, content is chunked without splitting table rows, and both BM25 and vector indexes are built. A structured extraction stage records selected numerical benefits with provenance.
2. **Question answering:** The user authenticates in the frontend. The application server validates authentication, identifies the requested plan(s), retrieves evidence from BM25 and/or semantic indexes, consults structured benefits for numerical questions, checks evidence sufficiency, and returns a cited answer or an abstention.
3. **Evaluation:** A 20–30 question set with verified answers is run against BM25 and semantic retrieval and the answer pipeline. Results capture retrieval/answer accuracy, extraction accuracy, latency, and token usage where applicable.

## Components

### User interface and authentication

- **Frontend:** Accepts a natural-language query and displays the answer, citations, or an insufficient-evidence response. The interface communicates with the application server over an HTTP API. Detailed visual design is outside the demo requirements.
- **Authentication:** Authentication is required. The frontend obtains/holds the selected provider's credential and includes it in protected requests.
- **Application server:** Validates credentials on every protected request before processing a question. Frontend-only authentication checks are insufficient.
- Provider, account model (individual accounts versus shared demo access), credential/session lifecycle, and account recovery are **TBD**.

### Ingestion pipeline

Process exactly six source PDFs:

1. **Document registry:** Assign each confirmed SBC a stable plan/document identity and record insurer, plan type, available plan-year metadata, and source URL when known. For supplied PDFs without URLs, retain the provided filename and delivery context; missing URLs do not prevent processing, but public availability must be verified to count toward the required corpus.
2. **PDF parsing:** Extract narrative text and tables using a parser that preserves table structure. Evaluate candidate parsers against the selected documents; parser choice is **TBD**.
3. **Normalization and provenance:** Retain plan identity, document identity, section heading, page number, and table/row context wherever available. Mark missing provenance rather than inventing it.
4. **Chunking:** Compare fixed-size and semantic strategies. Keep each table row intact and include its header/context. Select and document a strategy based on the evaluation set.
5. **Index construction:** Build a BM25 keyword index and a semantic vector index using sentence-transformer embeddings generated locally. Vector-index technology and hosting are **TBD**; embeddings must not require a hosted embedding API.
6. **Structured benefit extraction:** Extract at least deductibles, ER cost sharing, copays, and out-of-pocket maximums per plan. Store each value with document, section, and page provenance when available; unknown/unreadable values remain missing rather than inferred.

Parser, embedding model, vector store/database service, exact chunk configuration, structured storage implementation, and ingestion invocation method are **TBD**. Local embedding generation is required; the vector index may be hosted by the separate database service once that choice is made.

### Retrieval and answer service

- **Plan resolution:** Identify the plan or plans named in the question. Behavior for ambiguous plan names is to request clarification rather than silently select a plan.
- **Structured lookup:** For numerical benefit questions, read the extracted per-plan record and retain its source reference.
- **BM25 retrieval:** Search parsed chunks using keyword ranking.
- **Semantic retrieval:** Embed the query locally and search the vector index.
- **Retrieval evaluation:** Run each retrieval method independently over the evaluation questions and record results by question type. Runtime fusion is not required initially; whether to add fusion or choose a method per question type is **TBD based on results**.
- **Evidence gate:** Before generation, require source evidence that supports the requested claim and has a usable plan/section citation. If absent, contradictory, or ambiguous, return an insufficient-evidence response and do not ask the LLM to supply the missing fact.
- **Answer synthesis:** Use the Gemini API only to synthesize a concise answer from verified structured values and retrieved evidence. Query and document embeddings remain local and do not use Gemini.
- Exact Gemini model identifier, prompt template, generation parameters, output schema, timeout/retry behavior, and citation validation are **TBD**. Read the Gemini API key from an environment variable; the exact variable name is **TBD**.
- **Citation validation:** Every factual answer includes plan name and SBC section, plus page when available. The server validates that citations refer to evidence supplied to the answer step; unsupported claims are rejected or converted to abstention.

Confidence thresholds are **TBD**; the initial evidence gate is provenance-based and must abstain whenever supporting evidence is missing or conflicting.

## Data and interfaces

### Source document and chunk records

Each indexed chunk must retain:

- Stable document and plan identity, including plan name and type; source URL when available, otherwise the supplied filename/delivery context.
- Chunk text and stable chunk identity.
- Section heading and page number when available.
- Table context sufficient to interpret each row, with rows never split across chunks.

Exact field names and serialization are **TBD**, but provenance is required for citations and extraction auditability.

### Structured benefit record

Each extracted benefit record must include:

- Plan/document identity.
- Benefit category and extracted value as represented in the SBC.
- Source section and page when available.
- Extraction status so missing, unreadable, or unverified values cannot be mistaken for zero or a confirmed value.

The initial benefit categories are deductible, ER cost sharing, copays, and out-of-pocket maximum. Detailed field taxonomy and storage technology are **TBD**.

### Logical request and response

```text
Authenticated question request
  credential: provider-defined (TBD)
  question: natural-language text

Answer response
  status: answered | insufficient_evidence | clarification_needed
  answer: concise response when supported
  citations: plan, SBC section, page when available
```

Transport, endpoint names, concrete JSON types, error codes, and streaming behavior are **TBD**. These logical fields describe required behavior, not a finalized wire contract.

## Data flow

### Ingestion and indexing

```text
Six SBC PDFs
  -> document registry
  -> table-aware parsing and provenance
  -> row-preserving chunking
  -> BM25 index + local embedding/vector index
  -> structured benefit extraction with source references
```

### Authenticated question answering

```text
User -> Frontend -> authenticated request -> Application Server
  -> validate credential
  -> resolve plan(s)
  -> structured benefit lookup + BM25 retrieval + semantic retrieval
  -> evidence sufficiency / conflict check
  -> insufficient evidence response OR LLM synthesis from supported evidence
  -> citation validation
  -> Frontend -> User
```

### Evaluation

```text
20–30 labeled questions + verified expected answers
  -> BM25 run / semantic run / answer pipeline
  -> retrieval and answer accuracy, extraction accuracy,
     latency, and token usage report
```

## Evaluation and operational decisions

- Keep expected answers and source references for the evaluation questions so retrieval and extraction can be checked against the SBCs.
- Compare BM25 and semantic retrieval independently and summarize results by question type.
- Measure answer and extraction accuracy, per-query latency, and token usage. Numeric pass thresholds are **TBD**; record baseline results for the demo.
- Re-ingestion/versioning behavior, database provider and vector support, persistence, logging, query retention, hosting, and operational monitoring are **TBD**.

## Remaining implementation decisions

- Authentication provider and whether access uses individual accounts or shared demo credentials.
- PDF parser, local embedding model, database provider/vector support, and structured record storage.
- Exact chunk settings and any retrieval fusion/reranking based on evaluation results.
- Gemini model identifier and UI framework.
- Concrete API schema, citation display format, confidence threshold, latency target, and deployment/query-retention policies.
