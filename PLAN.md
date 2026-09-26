# Implementation Plan: SBC RAG Demo

This plan records the agreed technology direction and tracks implementation. The six received PDFs are approved as a provisional development/evaluation corpus, but remain unverified as SBCs and as publicly sourced documents. Phase 1's frontend/API scaffold, Firebase auth foundation, Neon migrations, and Render Blueprint are implemented. Phase 2 upload, parsing, chunking, inspection, and automatic API-triggered ingestion are implemented in code; deployed resource qualification and full corpus review remain pending. Phase 3 benefit extraction and review scaffolding is implemented on top of parsed pages. Phase 4 retrieval and evaluation tooling is implemented, while labeled runs remain pending. Phase 5's deterministic answer and session-only follow-up flow is implemented in code; measured answer quality remains pending. Phase 7's required Gemini-written replies are implemented and enabled locally; deployment and measurement remain pending.

Evidence review fixes retain every extracted table row, exclude ineligible documents from retrieval, require usable benefit sections, and abstain when requested candidates are ambiguous or conflicting. Numeric lower/higher comparisons identify an outcome only for comparable values, and mixed coverage types require clarification. The parser orders table rows and text by page position, assigns row section and network context from detected preceding headings, and filters table-positioned text from chunks. Existing stored chunks need re-ingestion to use the revised parser; existing verified benefits need section review after migration `006`. Semantic paraphrase matching remains constrained by the source-row term gate until labeled corpus evaluation supports a safe broader rule.

The FastAPI service now triggers the same parsing, chunking, candidate extraction, embedding, and readiness pipeline after an admin upload or Retry. Neon stores queued work; startup and admin document refresh resume interrupted jobs, with at most two automatic attempts before a visible failure. The local `python -m app.pipeline` command remains available for maintenance. Successful admin uploads become `approved` and queryable automatically after all stages complete and both chunk strategies have usable embeddings. Documents without an admin uploader retain `ready` or `ready_with_warnings`. Isolated issues remain visible as warnings; critical failures stay unavailable. Migration `008` adds the durable queue marker and attempt count. Full-corpus processing and Render memory qualification remain pending.

## Selected stack

- **Runtime/API:** Python 3.11 and FastAPI for ingestion commands, retrieval, answer logic, and the authenticated HTTP API.
- **Frontend:** React + TypeScript with shadcn/ui; serve as a Render static site and call the FastAPI API.
- **Authentication/roles:** Firebase Authentication on the no-cost Spark plan for email/password or social login. FastAPI verifies ID tokens for every protected request. A local one-time admin bootstrap command assigns Firebase custom claims; no public self-promotion endpoint.
- **Persistent data:** Neon Postgres Free for plan/document metadata, uploaded PDF bytes, parsed pages/rows/chunks, structured benefit candidates and reviews, provenance, processing state, and evaluation results. Do not expose Neon credentials to the browser.
- **Semantic retrieval:** Generate document and query embeddings with `sentence-transformers/all-MiniLM-L6-v2` in the FastAPI service, using the same configurable model version. The local maintenance command uses that same pipeline. Persist queryable document embedding values as ordinary per-chunk data in Neon; Neon does not perform vector search and pgvector is not used. The API currently builds an in-memory FAISS index for each semantic request. No embedding API or shared filesystem is required. Render memory fit remains **TBD** after a local macOS embedding run for one PDF exceeded the free service's 512 MiB limit.
- **Keyword retrieval:** `rank-bm25` over the same canonical chunks, independently measurable from semantic search.
- **PDF handling:** `pdfplumber` first; evaluate actual SBC output and add Camelot only for tables where it demonstrably improves row/cell structure.
- **Answers, deterministic path:** Deterministic formatting for structured numeric lookups and comparisons, citations, clarification, and abstention. This path decides every answer and is the fallback response when Gemini is unconfigured, unavailable, or returns invalid output.
- **Answers, Gemini responses (required, Phase 7):** Gemini writes only answers built from retrieved source rows. A rules-based check skips it for structured-benefit answers, clarifications, and insufficient-evidence replies, which return the deterministic text. The backend keeps status and citations and rejects replies with numbers absent from the evidence or missing a checked value.
- **Deployment:** Render Free static site + web service; Neon and Firebase are external managed services. Expect API sleep/cold starts and ephemeral Render filesystems. Store durable state in Neon. Do not require a custom domain or paid persistent disk.
- **Uploaded source files:** Store modest PDFs as PostgreSQL binary data in Neon for the initial six-plan demo to avoid another account/service and keep uploads durable. Impose a documented upload-size limit below provider/request limits. If corpus size outgrows database storage, revisit object storage only after verifying a no-card option.
- **Ingestion execution:** An admin upload or Retry queues a document in Neon and schedules the full pipeline after the FastAPI response. A database advisory lock serializes processing; startup and admin document refresh resume interrupted work. Two interrupted attempts stop automatic retries and require admin Retry. Render sets the configurable embedding batch size to 1 to reduce peak memory. `python -m app.pipeline`, `app.ingest`, and `app.embed` remain maintenance commands. Parsed provenance, stage outcomes, warnings, and embeddings are stored in Neon. No uploaded file or generated index depends on Render's ephemeral filesystem.
- **Evaluation/tests:** pytest for backend/parser/retrieval/auth/citation/evidence behavior; frontend checks as appropriate. Store a versioned 20–30 question evaluation manifest with verified expected values and source locations. Record accuracy, latency, Gemini token usage, retrieval results by method/question type, and extraction accuracy.
- **Secrets:** Environment variables for Neon connection string, Firebase project/service credentials, and deployment configuration. Privileged Firebase credentials exist only in local admin tooling or protected server secrets; never in React or source control.

## Retrieval and chunking experiment

- The two retrieval methods are **BM25 keyword retrieval** (`rank-bm25`) and **semantic vector retrieval** (local sentence-transformer embeddings searched with local FAISS). These methods differ in how they find relevant chunks; neither replaces the other in the baseline evaluation.
- The two chunking strategies are **fixed-size chunking** and **semantic/section-aware chunking**. Both must preserve table rows and the headers/context needed to interpret them.
- Evaluate the four combinations (BM25 + fixed-size, BM25 + semantic/section-aware, vector + fixed-size, vector + semantic/section-aware) against the same labeled questions and report retrieval/answer results by question type.
- Add an **admin-only evaluation playground** that lets an admin select a retrieval method and chunking strategy, then submit a question and inspect answer status, citations, and diagnostics. This is an evaluation control, not an unreviewed production routing knob: ordinary user mode uses the measured default configuration; admins can compare configurations and inspect detailed scores/run traces.
- Store versioned chunks for both strategies and associate each retrieval run with its chunking strategy, retrieval method, model/version, and top-k/configuration so results are reproducible. Do not duplicate original PDFs or verified benefit records for each strategy.
- Numerical questions use unambiguous, cited structured candidates or explicitly verified records; selected retrieval/chunking settings affect source-evidence retrieval and diagnostics.

## Ordered implementation phases

### Phase 1 — Corpus and runnable project skeleton

- **Completed project setup:** Six PDFs have been received, provisionally classified in `ARCHITECTURE.md`, and recorded with available file identity/provenance fields in `data/source-documents/received/metadata.json`. Unknown metadata remains null; the files are the provisional development corpus but remain unverified as SBCs/public sources.
- **Scaffold added:** React + TypeScript + Vite frontend with Firebase email/password registration/sign-in, a combined admin Plans/document upload and diagnostics page, optional benefit review, retrieval playground, and evaluation controls. Admin navigation reads the Firebase custom claim for presentation; server authorization remains authoritative. FastAPI chat uses queryable provisional evidence and supported benefit records for deterministic answers.
- [x] Establish a small Python backend and React TypeScript frontend layout; ingestion/evaluation/test directories will be added with those phases.
- [x] Add dependency/configuration files, local development instructions, `.env.example` containing names only, and ignores for secrets/build outputs.
- [x] Add Firebase registration/sign-in and FastAPI ID-token verification; Neon relational schema/migration with ordinary embedding values and no pgvector; FastAPI health/API skeleton; local admin-claim bootstrap command; and Render Blueprint without embedded secrets. Protect each authenticated/admin route when it is introduced.
- [x] Document local run and Render deployment setup, including manual provider configuration, cold starts, and free-tier limits.

**Milestone:** Phase 1 implementation is complete. Local commands and deployment configuration are documented. A real deployment still requires Firebase/Neon/Render accounts, credentials, and the manual environment settings in README; external resources have not been provisioned from this repo.

### Provisional corpus and final SBC qualification

- [x] Use the six received PDFs as the active provisional development/evaluation corpus; preserve their actual document type and their unverified SBC/public-source status.
- [x] Keep provisional corpus membership distinct from SBC qualification. The set includes dental and vision summaries and has not been established as six standardized medical SBCs.
- [ ] Resolve final corpus qualification as exactly six public medical SBCs spanning HMO/PPO/HDHP, or document a later approved change to that target. This does not block development or provisional evaluation.

**Milestone:** The six supplied files are used as a clearly labeled provisional corpus. Final SBC/public-source qualification remains an open acceptance item.

### Phase 2 — SBC parsing, provenance, and table-safe chunks

- [x] Build source-document registry and real admin PDF upload, storing original PDFs and upload status in Neon.
- [x] Implement the local ingestion CLI: fetch pending uploads, parse pages/tables with pdfplumber, preserve section/page and table headers, and report parse issues.
- [x] Keep uploads unavailable until the full pipeline completes; automatically approve successful admin uploads for questions without a verification click.
- [x] Compare fixed-size chunking with semantic/section-aware chunking while never splitting a table row from its interpretive headers/context.
- [ ] Review parser output on all six provisional documents; add Camelot only where it improves table fidelity. If a qualifying SBC corpus is later selected, repeat corpus-specific parser review.
- [x] Add parser/chunker fixtures covering provenance, intact rows, missing sections, and malformed PDF input.

**Milestone:** Upload, local parsing/chunking, inspection, and document review work for the provisional corpus. Review the parsed output on each supplied document before relying on it for provisional evaluation.

### Phase 3 — Structured benefit extraction and admin review

- [x] Define typed candidate records for deductible, ER cost sharing, copays, and out-of-pocket maximum, preserving source wording, available page/section, and recognizable network/family/individual/coinsurance dimensions.
- [x] Add table-aware candidate extraction that carries benefit labels and period context across continuation rows, separates individual/family and network values, and keeps all candidates pending review. Page text remains a fallback where tables are unavailable; extraction remains a review aid, not an authoritative parser.
- [x] Add regression coverage for the Aetna out-of-pocket maximum table, multi-network continuation rows, values combined in one cell, and repeated headerless table cells.
- [x] Add admin-only API operations and a benefit review UI to extract, inspect, correct, and assign review status, with reviewer UID and timestamp.
- [x] Add an idempotency index for repeated extraction of the same source line.
- [x] Gate answers on queryable documents and unambiguous values with page and section citations; admin verification remains optional. End-to-end corpus evaluation remains open.
- [x] Measure extraction accuracy against `evaluation/extraction_labels.json` with `python -m app.evaluate`: 31/33 fields (2026-09-25), up from 26/33.
- [x] Extraction fixes from that audit (2026-09-25): "No annual deductible" is a none value; "Emergency services" rows are ER cost sharing; flat "per visit" primary care and specialist amounts are copays; out-of-network reimbursement schedules ("Amount over", "up to") are not copays; tables continued on the next page keep the previous page's network headers and open section.
- [x] Answer fixes from the same audit: "yearly"/"annually" are period words like "year"/"annual" in the source gate; a question naming a year that doesn't match the plan's recorded plan year (or has none) abstains.

**Milestone:** Automatic extraction and optional admin review are implemented. Measured accuracy must identify the provisional corpus.

### Phase 4 — BM25 and semantic retrieval baselines

- [x] Implement local sentence-transformer embedding generation for queryable chunks and persist vectors with chunk IDs/model version in Neon; construct the FAISS index in the API process from current embeddings for semantic searches.
- [x] Add plan/document/section filtering without losing provenance.
- [ ] Create 20–30 evaluation questions with manually checked expected evidence locations, answer labels, and question types drawn from the six provisional documents; label results provisional and corpus-scoped. The manifest and runner are in place, but labels must be authored after reviewing actual ingested documents.
- [x] Implement four-combination evaluation over the same manifest and persist aggregate/per-question metrics without retaining question text.
- [x] Add an admin-only evaluation playground for selecting BM25 or semantic search and fixed-size or semantic/section-aware chunks, plus detailed ranked evidence traces.
- [x] Record latency and retrieval scores per question/configuration, retaining both methods for comparison.
- [ ] Select runtime retrieval behavior from measured results. Ordinary chat temporarily defaults to BM25 with section-aware chunks until labeled runs exist.

**Milestone:** Retrieval, playground, and reproducible evaluation runner are implemented. Provisional retrieval findings remain pending reviewed parser output, the 20–30 manually labeled questions, and actual runs.

### Phase 5 — Authenticated answer flow and diagnostics

- [x] Require Firebase token verification on protected FastAPI requests and admin custom claims on upload/review/evaluation/diagnostic endpoints. Targeted authorization review remains open.
- [x] Send the previous in-memory question and resolved plan IDs for short follow-ups. New chat, sign-out, and reload clear this context; no chat-history persistence or history API was added.
- [x] Resolve queryable plans and ask for clarification for ambiguous names.
- [x] Route numerical lookups and comparisons through supported structured records; quote retrieved, provenance-bearing source rows for broader coverage questions.
- [x] Apply readiness, value, dimension, conflict, and citation gates with explicit clarification or abstention.
- [x] Implement deterministic, cited answer formatting without Gemini. Measured answer accuracy remains pending the labeled manifest and reviewed corpus.
- [x] Show basic diagnostics to all users; show admins detailed answer traces and document/parse/benefit/embedding health.
- [ ] Use measured results to select ordinary-user defaults; retain explicit configuration selection in the evaluation playground.
- [x] Add targeted tests for readiness, warning and critical outcomes, supported candidate answers, affected-question abstention, and admin stage diagnostics. Broader corpus evaluation remains open.

**Milestone:** The Phase 5 flow is implemented in code. End-to-end review against actual ingested documents, targeted tests, and measured answer accuracy remain open before treating the milestone as validated.

**Kaiser parsing and answer repair (2026-09-25):** Recognized the Traditional Plan PDF's title-case benefit headings, carried sections into text candidates and table rows, stored text wording in chunk provenance, and accepted the source's literal `None` deductible without converting it to zero. Plan and drug deductible rows are distinguished. A PDF-to-BM25-to-answer regression covers cited urgent-care, emergency-department, and deductible answers plus abstention for missing out-of-network evidence. The configured Neon uploads were reprocessed: the Traditional Plan document is `ready` with no warnings; the separate Kaiser WA document is `ready_with_warnings` because 18 candidates remain ambiguous and 17 lack a detected section. Both now return BM25 evidence. Backend deployment and broader provisional-corpus accuracy measurement remain pending.

**Automatic ingestion (2026-09-25):** New admin uploads and Retry now start the existing pipeline in a FastAPI background task. Neon records queued work and attempts; startup and document-list requests recover interrupted work, and a database advisory lock limits ingestion to one document at a time. Migration `008` was applied to the configured development Neon database. A disposable Guardian vision upload through the authenticated API path completed all four stages, produced 13 chunks, reached `ready_with_warnings`, and was removed afterward. A repeat with Render's batch-size-1 setting also reached `ready_with_warnings`; both temporary uploads and plans were removed. Backend tests and the frontend build passed. Render deployment and its 512 MiB memory fit remain unverified; the batch-size-1 local API run peaked at about 555 MiB.

**Admin document deletion (2026-09-25, user-approved addition):** Admin-only `DELETE /api/admin/documents/{document_id}` permanently removes a document; pages, chunks, embeddings, and benefit records cascade, and the linked plan is removed when no other document references it. Queued or processing documents return 409. The Plans page shows a trash icon per document with a confirmation prompt. Backend tests cover deletion, the processing guard, and non-admin rejection. The Plans list no longer shows review/corpus status labels or a Reject button; the review API endpoint remains.

**Automatic admin approval (2026-09-25):** Admin uploads are treated as prevalidated by the uploader and become `approved` after successful parsing, extraction, and embedding. The document Verify button was removed. Source SBC/public availability remains a separate, unverified corpus field. The pipeline remains necessary to make evidence searchable and answerable.

### Phase 6 — Deployment, evaluation, and documentation

**Answer accuracy regression tests (2026-09-25):** Added a focused offline suite checking
final deterministic/fallback text, exact benefit amounts and source citations, competing
network/family contexts, plan-value associations, comparison winners, and abstention.
Real provisional Kaiser PDF cases share the existing parsing/extraction fixture; competing
benefit contexts use synthetic records. Initial results were 15 passed and 3 strict
expected failures. The compound source-bundle repair below resolves those answer
gaps without changing the structured candidate records. The 25-question manifest
contains labels; the admin runner still scores retrieval only. Gemini quality and
all four retrieval configurations remain unmeasured.

**Kaiser hospitalization X-ray answer (2026-09-25):** The evidence gate matched every
question term only against row text. It therefore missed “hospitalization” in the section
heading and treated PDF “X-rays” as different from query “xray”, despite retrieving the
relevant chunk. Source matching now includes the detected section heading and normalizes
these written forms; the answer still quotes the source row, “$500 per admission,” and
cites page 1, Hospitalization Services. A real-PDF regression covers this question.

**Provisional PDF answer checks (2026-09-25):** Added 25 answer, 25 citation, and 25
missing-evidence abstention checks using all six received PDFs, parsed benefits and
section-aware chunks, and real BM25 search in an in-memory corpus. Initially all
25 full-answer checks had strict expected failures, while six citation checks
passed and 19 had strict expected failures. The newer audit below records the
current results. All 25 missing-evidence abstention checks pass. These are
offline corpus-scoped regressions, not a live API/Gemini run or
results for the other retrieval configurations; measured deployment quality remains
open.

**Kaiser mail-order refill answer (2026-09-25):** Removed the arbitrary four-term
limit that forced specific natural-language coverage questions into clarification
before retrieval. The original coverage gate still requires the question terms in
one cited source row/section; compound questions now use the bundle path described
below. The real PDF regression returns the listed “Most generic
refills through our mail-order service” cost of $20 for up to a 100-day supply,
with page 1 and the Prescription Drug Coverage section. The broader question
matching also made one Aetna POS Payment Limit citation check pass; the initial
corpus citation baseline was 6/25, with 19 strict expected failures.

The next brand-name mail-order turn exposed a separate follow-up issue: the answer
path appended the previous generic-refill question to the current specific question,
so no single source row could pass the evidence gate. Numeric category inheritance
now applies only to explicit elliptical follow-ups or comparisons, without appending
the previous question. A real-PDF regression checks the brand-name row's $40 cost
for up to a 100-day supply and its page 1 Prescription Drug Coverage citation.

**Six-document line and answer audit (2026-09-25):** Reparsed all 22 pages and
checked all 983 extracted text lines against both chunk strategies. Source-line
provenance now retains table-positioned lines when table extraction drops words;
the repeatable check finds zero lost extracted words at page level. This does not
establish complete fact interpretation. Group Health table rows without detected
headings can now cite their service label, and specific copay questions exclude
unrelated ambiguous services. Plan aliases distinguish Guardian's dental and
vision products. Explicit multi-context numeric questions can report all cited
structured values; the Aetna HMO deductible/maximum and Aetna POS network/scope
deductible questions now pass their full-answer checks. Current offline results:
Before the compound source-bundle path, results were 4/25 full answers, 10/25
citations, and 25/25 missing-source abstentions. Gemini
quality and deployed behavior remain unmeasured.

**TBD — comprehensive answer coverage:** The request to cover every piece of
information and achieve 100% accuracy for arbitrary questions exceeds the
current four-category structured schema and 25-question evaluation. There is
no finite test of every possible natural-language question. Expand the labeled
set by source row, table context, notes, exclusions, and cross-plan combinations;
continue expanding beyond the now-passing 25-question set before claiming broad
accuracy. Reprocessing existing documents to use revised provenance replaces
their benefit records, including optional admin corrections or verification, so
review stored records before a maintenance reprocess.

**Compound source-bundle repair (2026-09-25):** BM25 now ranks candidate chunks,
then the deterministic gate can select multiple source rows and adjoining notes
for a compound question. It keeps table network/family headers, requires each
requested source label, and returns separate citations where facts span sections
or pages. Simple structured lookups and the independent semantic playground
remain. A POS infertility-treatment query now reports that the summary states
no single price and qualifies cost sharing by service and location, citing page 4.
All 25 labeled full answers, 25 citations, and 25 missing-source abstentions now
pass against freshly parsed PDFs. The same 25 deterministic answer/citation checks
passed in a read-only run against the configured Neon documents. The complete
backend suite passes (199 passed, 1 skipped); the frontend build passes. Live
Gemini quality, all four retrieval configurations, arbitrary questions, and
the deployed service remain unmeasured.

**Deductible query regression (2026-09-25):** A live `what is deductable`
question returned no BM25 ranks although the Aetna POS PDF and approved Neon
document contain the deductible table. Normalize that spelling at the answer
boundary. A bare deductible question now selects the cited deductible row and
its adjacent family row, preserving both network headers. The exact question
passes against freshly parsed PDFs and a read-only query of the configured
approved Neon document. This identifies a query interpretation/retrieval gap;
the parser retained the needed values. Other unlabeled questions still require
separate evaluation before broad accuracy claims.

**Kaiser inpatient label regression (2026-09-25):** The compound gate previously
required an `Inpatient Coverage` row, which exists in the Aetna summaries but
not the Kaiser Traditional summary. Its hospital cost appears under
`Hospitalization Services You Pay` in the `Room and board` row. The gate now
accepts either source label for an inpatient hospital question. A PDF-based
regression and a read-only query of the approved Neon document both return
`$500 per admission` with a page 1 hospitalization citation. The exact live
question text is pending from the user; this regression covers the triggering
inpatient/hospital label path.
More specific inpatient psychiatric and detoxification questions retain their
own source labels, and deductible-specific questions do not use the generic
hospital cost row.

**Corpus-wide source catalog and selector sweep (2026-09-25):** Replaced the
single-row coverage gate with a provenance-backed source catalog for general
coverage questions. It retains table headers, joins continuation rows and nearby
qualifications, and allows a request to resolve to multiple cited passages. A
full selector sweep now reaches all 283 extracted benefit entries across the six
received PDFs and all 43 exclusion passages are reachable with explicit
exclusion intent; the separate line-retention check still covers all 983
extracted lines across 22 pages. The labeled evaluation remains 25 questions,
and selector sweeps do not establish accuracy for every possible phrasing or
validate every extraction. Backend tests: 201 passed, 1 skipped. Frontend
production build passes. The configured Neon 25-question checks were performed
read-only in an earlier run; the latest source-catalog changes were verified
against the offline parsed-PDF corpus, not re-run against Neon or deployed Gemini.
Universal 100% answer accuracy remains unprovable; increase and manually verify
the evaluation set before making broader claims.

**Evaluation manifest v3 (2026-09-25):** Rebalanced `evaluation/questions.json` to
30 questions: 18 single-plan answers, 3 cross-plan comparisons, 5 expected
abstentions, and 4 expected clarifications. Each question records
`expected_status`, `required_phrases`, and coverage `tags`, and may record
`forbidden_amounts`. Additions cover plain-language and synonym wording, later-page
evidence, not-covered values, a false premise, a missing network column, an absent
deductible or premium, partial support, a wrong plan year, missing, ambiguous, or
unknown plans, and mixed coverage types. Admin retrieval scoring uses only the 21
answerable questions. Deterministic results: 17/21 answerable questions and 8/9
abstention/clarification questions pass; five `known_gap` questions are strict
expected failures pending fixes. Backend tests: 189 passed, 9 xfailed, 1 skipped.
Expected answers for new questions were checked against parsed PDF text and still
need manual page-level verification; Neon and Gemini runs of v3 are pending.

**Hybrid retrieval and offline evaluation report (2026-09-25):** Added hybrid
retrieval (BM25 and semantic top 20, reciprocal rank fusion with k = 60) to the
retrieval module, admin playground, and evaluation runner; migration `009` allows
`hybrid` evaluation runs. Added `python -m app.evaluate`, which measures all six
retrieval configurations, deterministic answer/citation/abstention accuracy,
extraction accuracy against `evaluation/extraction_labels.json` (33 fields), and
optional Gemini tokens and latency. First results: retrieval hit rate 71–90%;
deterministic answers 25/30 in every configuration; 21/21 removed-evidence
abstentions; extraction 26/33 fields; Gemini about 600 tokens per query, 4.2 s mean
latency, and 4 of 30 calls timed out at 10 s. Ordinary chat stays on BM25 with
section-aware chunks. Whether to skip Gemini for structured answers or shorten its
timeout to meet the 2 s latency target is **TBD** pending user decision; migration
`009` still needs to be applied to Neon.

- [ ] Deploy React static site and FastAPI web service on Render Free; configure Firebase authorized domains and server secrets; connect Neon Free.
- [ ] Verify upload-to-automatic-pipeline-to-answer against Neon and on the deployed Render service; measure peak memory, CPU time, and cold-start behavior. Render Free compatibility is **TBD** because the current local embedding path exceeded 512 MiB even at batch size 1.
- [ ] Run the labeled set against the provisional corpus; report answer/extraction accuracy, per-method retrieval results by question type, latency, and Gemini token usage, clearly scoped to those documents.
- [ ] Document actual chunking/parser/vector choices and observed limits, free-tier behavior, results, and what additional budget would change.

**Milestone:** The deployed demo is reproducible within no-card free-tier constraints and reports measured evidence quality.

### Phase 7 — Gemini responses (required)

Gemini phrasing was changed from an optional phase to a required phase on 2026-09-25 at the user's request. The same day, the user asked for Gemini to write all replies instead of selecting fixed templates, falling back on API errors and on replies that fail a numeric evidence check. The evidence gate is unchanged.

Later that day, the user asked to follow the original project spec over that decision: keep the LLM step thin and add a rules-based check that skips Gemini when structured data already answers the question. Gemini now writes only retrieved-source answers. The user also asked to treat the six PDFs as verified SBCs.

- [x] Add a Gemini adapter after the deterministic answer path, controlled by `GEMINI_ENABLED`.
- [x] Skip Gemini by rule for structured-benefit answers, clarifications, and insufficient-evidence replies (`skip_reason`).
- [x] Have Gemini write retrieved-source answers from the reply type, deterministic draft, and checked facts. The server keeps status and citations. Record per-response token use and latency.
- [x] Return the deterministic answer when Gemini is unconfigured, the API call fails, or the reply contains a number absent from the evidence or omits a checked value.
- [x] Enable Gemini locally with a configured API key.
- [ ] Enable Gemini on the deployed Render API service with `GEMINI_API_KEY` set as a service secret.
- [x] Compare quality, latency, and token use with deterministic output (`python -m app.evaluate --gemini`): 17 of 30 queries call Gemini, served accuracy equals deterministic (83%), mean / p95 latency 757 / 1,668 ms, 408 tokens per query.
- [x] Show the offline report (accuracy, latency, tokens per query) on the admin Evaluation page via `GET /api/admin/evaluation/report`.

**Milestone:** Gemini-written replies are served in the demo, with measured quality, latency, and token use reported alongside the deterministic baseline.

## Definition of done

- The six received files are the active provisional corpus, with document types and unverified SBC/public-source status represented accurately. Final six-public-SBC qualification remains TBD.
- Admin uploads are durable; ingestion is real, locally executed, reviewable, and protected by server-enforced Firebase roles.
- Parsing and chunks preserve table interpretation context and provenance.
- BM25 and local semantic retrieval are independently evaluated over 20–30 labeled questions.
- Numeric benefits are extracted with traceable provenance; optional human verification and measured accuracy remain available.
- Answers cite the source plan and section/page when available; unsupported, ambiguous, untraceable, or conflicting claims abstain or request clarification.
- Deterministic answers work on their own as the fallback; Gemini writes replies in the demo and remains evidence-bound.
- Basic diagnostics are visible to users, advanced diagnostics to admins.
- README reports setup, free deployment limitations, chunking/retrieval/extraction decisions and measurements, and budget tradeoffs.
