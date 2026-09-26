# Evaluation results (2026-09-26 01:04 UTC)

Manifest `provisional-v3`: 30 questions (21 answerable, 9 abstain/clarify). Offline run over freshly parsed PDFs; latency excludes Neon, network, and auth.

## Retrieval (answerable questions, top 5)

| Method | Chunking | Hits | Hit rate | MRR | Mean latency |
|---|---|---|---|---|---|
| bm25 | fixed_size | 19/21 | 90% | 0.603 | 2.5 ms |
| bm25 | section_aware | 19/21 | 90% | 0.609 | 2.6 ms |
| semantic | fixed_size | 18/21 | 86% | 0.540 | 4.6 ms |
| semantic | section_aware | 15/21 | 71% | 0.422 | 4.5 ms |
| hybrid | fixed_size | 19/21 | 90% | 0.680 | 7.4 ms |
| hybrid | section_aware | 16/21 | 76% | 0.541 | 8.3 ms |

## Deterministic answers

| Method | Chunking | Correct | Answerable correct | Citations | False refusals | Refusals correct | Mean / p95 latency |
|---|---|---|---|---|---|---|---|
| bm25 | fixed_size | 90% | 18/21 | 18/21 | 3 | 9/9 | 13 / 32 ms |
| bm25 | section_aware | 90% | 18/21 | 18/21 | 3 | 9/9 | 13 / 38 ms |
| semantic | fixed_size | 90% | 18/21 | 18/21 | 3 | 9/9 | 18 / 38 ms |
| semantic | section_aware | 90% | 18/21 | 18/21 | 3 | 9/9 | 18 / 36 ms |
| hybrid | fixed_size | 90% | 18/21 | 18/21 | 3 | 9/9 | 18 / 38 ms |
| hybrid | section_aware | 90% | 18/21 | 18/21 | 3 | 9/9 | 18 / 37 ms |

Abstention when labeled source evidence is removed: 21/21.

## Extraction

31/33 fields correct (94%); 0 missing network context, 0 wrong, 1 flagged ambiguous, 1 missing.

- flagged: candidate-aetna-oamc-2017 er_cost_sharing in (expected $100)
- missing: candidate-guardian-vsp-vision-2017 copay first service  (expected $20)

## Gemini (runtime configuration)

- Calls: 17 of 30 queries; skipped by rule: {'skipped_no_answer': 12, 'skipped_structured_answer': 1}; Gemini text served: 16; fallbacks: {'timeout': 1}
- Mean tokens per call: 546 input, 126 output, 672 total; per query (skipped = 0): 381
- Mean Gemini latency per call: 3999 ms; end-to-end mean / p95: 2279 / 8088 ms
- Served-answer accuracy: 90%
