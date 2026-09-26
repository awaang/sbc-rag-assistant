"""Offline evaluation over freshly parsed SBC PDFs.

Measures retrieval (hit rate, MRR, latency) for each retrieval method and chunk strategy,
deterministic answer/citation/abstention accuracy, structured-extraction accuracy, and
optionally Gemini token use and latency. Uses an in-memory stand-in for Neon, so latency
excludes database, network, and authentication time.

    python -m app.evaluate            # deterministic only
    python -m app.evaluate --gemini   # also calls Gemini once per question
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import statistics
import time
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from dotenv import load_dotenv

from app.answering import answer_question
from app.benefits import extract_candidates
from app.ingestion import build_chunks, parse_pdf
from app import retrieval

ROOT = Path(__file__).resolve().parents[2]
SOURCE_DIR = ROOT / "data/source-documents/received"
AMOUNT = re.compile(r"\$\s?\d[\d,]*(?:\.\d+)?|\b\d+(?:\.\d+)?\s?%")
METHODS = ("bm25", "semantic", "hybrid")
STRATEGIES = ("fixed_size", "section_aware")
RUNTIME = ("bm25", "section_aware")
TOP_K = 5


class Rows:
    def __init__(self, rows):
        self.rows = rows

    def fetchall(self):
        return self.rows


class PDFCorpus:
    """Answers the SQL issued by retrieval and answering from parsed PDFs."""

    def __init__(self, plans, chunks, benefits, vectors, excluded=frozenset()):
        self.plans, self.chunks, self.benefits = plans, chunks, benefits
        self.vectors, self.excluded = vectors, excluded

    def without_evidence(self, document_ids):
        return PDFCorpus(self.plans, self.chunks, self.benefits, self.vectors, frozenset(document_ids))

    @staticmethod
    def _filters(sql, params, start):
        values, index = {}, start
        for name in ("plan_id", "document_id", "section"):
            if f"d.{name} = %s" in sql or (name == "section" and "ILIKE %s" in sql):
                values[name] = params[index]
                index += 1
        return values

    def _chunks(self, strategy, filters):
        return [row for row in self.chunks if row["chunk_strategy"] == strategy
                and row["document_id"] not in self.excluded
                and filters.get("plan_id") in (None, row["plan_id"])
                and filters.get("document_id") in (None, row["document_id"])
                and (filters.get("section") is None
                     or filters["section"].strip("%").lower() in json.dumps(row["provenance"]).lower())]

    def execute(self, sql, params=()):
        if "FROM plans p JOIN documents" in sql:
            return Rows(self.plans)
        if "FROM benefit_records b" in sql:
            plan_ids, category = params[:2]
            return Rows([row for row in self.benefits if row["plan_id"] in plan_ids
                         and row["category"] == category and row["document_id"] not in self.excluded])
        if "FROM chunk_embeddings ce" in sql:
            rows = self._chunks(params[0], self._filters(sql, params, 5))
            return Rows([{"chunk_id": row["chunk_id"], "embedding_values": self.vectors[row["chunk_id"]],
                          "model_fingerprint": params[4]} for row in rows])
        if "FROM chunks c JOIN documents d" in sql:
            return Rows(self._chunks(params[0], self._filters(sql, params, 2)))
        raise AssertionError(sql)


def build_corpus(metadata, with_embeddings=True):
    plans, chunks, benefits, ids = [], [], [], {}
    for plan_id, document in enumerate(metadata["documents"], 1):
        data = (SOURCE_DIR / document["original_filename"]).read_bytes()
        if hashlib.sha256(data).hexdigest() != document["sha256"]:
            raise SystemExit(f"SHA-256 mismatch for {document['original_filename']}")
        pages = parse_pdf(data)
        plan = {"plan_id": plan_id, "insurer": document["insurer"], "plan_name": document["plan_name"],
                "plan_type": (document["plan_type"] or "unknown").lower(),
                "coverage_type": document["coverage_type"], "plan_year": document.get("plan_year")}
        plans.append(plan)
        ids[document["document_id"]] = plan_id
        for strategy, items in build_chunks(pages).items():
            for item in items:
                chunks.append({"chunk_id": len(chunks) + 1, "document_id": plan_id, "plan_id": plan_id,
                               "plan_name": plan["plan_name"], "original_filename": document["original_filename"],
                               "chunk_strategy": strategy, "chunk_text": item["text"],
                               "page_start": item["page_start"], "page_end": item["page_end"],
                               "provenance": item["provenance"]})
        for candidate in extract_candidates(pages):
            benefits.append({"benefit_id": len(benefits) + 1, "plan_id": plan_id,
                             "category": candidate.category, "value_text": candidate.value_text,
                             "dimensions": candidate.dimensions, "verification_status": candidate.status,
                             "reviewed_at": None, "source_section_verified": False,
                             "section": candidate.section, "page_number": candidate.page_number,
                             "parse_status": "parsed", "document_id": plan_id,
                             "original_filename": document["original_filename"],
                             "plan_name": plan["plan_name"]})
    vectors = {}
    if with_embeddings:
        encoded = retrieval.encode_texts([row["chunk_text"] for row in chunks])
        vectors = {row["chunk_id"]: vector.tolist() for row, vector in zip(chunks, encoded)}
    return PDFCorpus(plans, chunks, benefits, vectors), ids


def amount_key(value):
    compact = value.replace(" ", "").replace(",", "")
    return (compact[0], Decimal(compact[1:-1] if compact.endswith("%") else compact[1:]))


def amounts(text):
    return {amount_key(value) for value in AMOUNT.findall(text)}


def normalize(text):
    return re.sub(r"[- ]+", " ", text.lower())


def score_answer(item, result):
    """Same criteria as tests/test_pdf_answer_evaluation.py."""
    if result["status"] != item["expected_status"]:
        return False
    if item["expected_status"] != "answered":
        return not result["citations"] and not AMOUNT.search(result["answer"])
    stated = amounts(result["answer"])
    forbidden = {amount_key(value) for value in item.get("forbidden_amounts", [])}
    return (amounts(item["expected_answer"]) <= stated and not forbidden & stated
            and all(normalize(phrase) in normalize(result["answer"]) for phrase in item["required_phrases"]))


def score_citations(item, result, filenames):
    if item["expected_status"] != "answered":
        return not result["citations"]
    citations = result["citations"]
    pages = set(item["expected_pages"])
    return (bool(citations)
            and all(any(c.get("document") == filenames[source] and c.get("page") in pages
                        for c in citations) for source in item["source_document_ids"])
            and all(c.get("page") in pages and c.get("section") for c in citations))


def ask(corpus, item, ids, method, strategy):
    context = [ids[source] for source in item["source_document_ids"]] or None
    started = time.perf_counter()
    result = answer_question(corpus, item["question"], context_plan_ids=context,
                             method_override=method, strategy_override=strategy)
    return result, (time.perf_counter() - started) * 1000


def evaluate_retrieval(corpus, questions, ids_by_sha):
    rows = []
    for method in METHODS:
        for strategy in STRATEGIES:
            observations = []
            for item in questions:
                expected = {ids_by_sha[sha] for sha in item["expected_document_sha256s"]}
                result = retrieval.retrieve(corpus, item["question"], method, strategy, top_k=TOP_K)
                matching = [row for row in result["results"] if row["document_id"] in expected
                            and any(row["page_start"] <= page <= (row["page_end"] or row["page_start"])
                                    for page in item["expected_pages"])]
                if item.get("require_all_documents"):
                    best = {}
                    for row in matching:
                        best[row["document_id"]] = min(best.get(row["document_id"], row["rank"]), row["rank"])
                    rank = max(best.values()) if expected <= set(best) else None
                else:
                    rank = min((row["rank"] for row in matching), default=None)
                observations.append({"question_id": item["question_id"], "question_type": item["question_type"],
                                     "tags": item.get("tags", []), "rank": rank,
                                     "latency_ms": result["timings"]["total_request_ms"]})
            rows.append({"method": method, "chunk_strategy": strategy, **summarize_ranks(observations),
                         "by_question_type": group_ranks(observations, "question_type"),
                         "questions": observations})
    return rows


def summarize_ranks(observations):
    n = len(observations)
    return {"question_count": n, "hits": sum(o["rank"] is not None for o in observations),
            "hit_rate": sum(o["rank"] is not None for o in observations) / n,
            "mrr": sum(1 / o["rank"] for o in observations if o["rank"]) / n,
            "mean_latency_ms": statistics.mean(o["latency_ms"] for o in observations)}


def group_ranks(observations, key):
    groups = {}
    for observation in observations:
        groups.setdefault(observation[key], []).append(observation)
    return {name: summarize_ranks(group) for name, group in sorted(groups.items())}


def evaluate_answers(corpus, questions, ids, filenames):
    configs = []
    for method in METHODS:
        for strategy in STRATEGIES:
            per_question = []
            for item in questions:
                result, latency = ask(corpus, item, ids, method, strategy)
                per_question.append({"question_id": item["question_id"], "question": item["question"],
                                     "question_type": item["question_type"], "expected_status": item["expected_status"],
                                     "status": result["status"], "answer_correct": score_answer(item, result),
                                     "citation_correct": score_citations(item, result, filenames),
                                     "latency_ms": latency, "answer": result["answer"],
                                     "citations": result["citations"], "_result": result})
            configs.append({"method": method, "chunk_strategy": strategy, **summarize_answers(per_question),
                            "questions": per_question})
    return configs


def summarize_answers(per_question):
    answerable = [q for q in per_question if q["expected_status"] == "answered"]
    refusals = [q for q in per_question if q["expected_status"] != "answered"]
    latencies = sorted(q["latency_ms"] for q in per_question)
    return {
        "answer_accuracy": sum(q["answer_correct"] for q in per_question) / len(per_question),
        "answerable_correct": sum(q["answer_correct"] for q in answerable),
        "answerable_total": len(answerable),
        "citation_correct": sum(q["citation_correct"] and q["answer_correct"] for q in answerable),
        "false_refusals": sum(q["status"] != "answered" for q in answerable),
        "refusals_correct": sum(q["answer_correct"] for q in refusals),
        "refusals_total": len(refusals),
        "mean_latency_ms": statistics.mean(latencies),
        "p95_latency_ms": latencies[max(0, round(0.95 * len(latencies)) - 1)],
    }


def evaluate_removed_evidence(corpus, questions, ids):
    passed = 0
    answerable = [item for item in questions if item["expected_status"] == "answered"]
    for item in answerable:
        sources = [ids[source] for source in item["source_document_ids"]]
        result = answer_question(corpus.without_evidence(sources), item["question"], context_plan_ids=sources,
                                 method_override=RUNTIME[0], strategy_override=RUNTIME[1])
        passed += (result["status"] in {"insufficient_evidence", "clarification_needed"}
                   and not result["citations"] and not AMOUNT.search(result["answer"]))
    return {"passed": passed, "total": len(answerable)}


FIELD_LABEL = {
    "deductible": re.compile(r"\s*(?:plan |calendar year )?deductible\b", re.I),
    "out_of_pocket_maximum": re.compile(r"\s*(?:plan )?(?:out[- ]of[- ]pocket|payment limit)", re.I),
    "er_cost_sharing": re.compile(r"\s*emergency", re.I),
}
SERVICE = {"primary care": r"primary care|\bpcp\b", "specialist": r"specialist",
           "office visit": r"office visit", "first service": r"first servic"}
NONE_VALUE = re.compile(r"\bnone\b|no annual deductible|no deductible", re.I)


def _scope(dimensions):
    if "family_context" in dimensions:
        return "family_member"
    if "family" in dimensions:
        return "family"
    if "individual" in dimensions:
        return "individual"
    return None


def _extracted_value(value_text):
    value = value_text.split(":", 1)[1] if ":" in value_text else value_text
    found = AMOUNT.search(value)
    if found:
        return amount_key(found.group())
    return "none" if NONE_VALUE.search(value) else None


def evaluate_extraction(corpus, labels, ids):
    fields = []
    for label in labels["fields"]:
        plan_id = ids[label["source_document_id"]]
        expected = "none" if label["value"] == "none" else amount_key(label["value"])
        matches = []
        for row in corpus.benefits:
            text = row["value_text"]
            if row["plan_id"] != plan_id or row["category"] != label["field"]:
                continue
            if label["field"] == "copay":
                if not re.search(SERVICE[label["service"]], text.split(":", 1)[0], re.I):
                    continue
            elif not FIELD_LABEL[label["field"]].match(text):
                continue
            network = {"IN-NETWORK": "in", "OUT-OF-NETWORK": "out"}.get((row["dimensions"] or {}).get("network"))
            if label["network"] and network not in {label["network"], None}:
                continue
            if label["scope"] and _scope(row["dimensions"] or {}) != label["scope"]:
                continue
            matches.append(row)
        usable = [row for row in matches if row["verification_status"] in {"pending_review", "verified"}]
        values = {_extracted_value(row["value_text"]) for row in usable}
        if not matches:
            outcome = "missing"
        elif not usable:
            outcome = "flagged"
        elif values == {expected} and all(row["page_number"] == label["page"] for row in usable):
            unlabeled = label["network"] and any(not (row["dimensions"] or {}).get("network") for row in usable)
            outcome = "incomplete" if unlabeled else "correct"
        else:
            outcome = "wrong"
        fields.append({**label, "outcome": outcome,
                       "extracted": [{"value_text": row["value_text"], "status": row["verification_status"],
                                      "page": row["page_number"], "section": row["section"]} for row in matches]})
    counts = {name: sum(f["outcome"] == name for f in fields) for name in ("correct", "incomplete", "wrong", "flagged", "missing")}
    return {"accuracy": counts["correct"] / len(fields), "total": len(fields), **counts, "fields": fields}


def evaluate_gemini(runtime_questions, questions, filenames, delay):
    from app.gemini import phrase_answer, skip_reason

    rows = []
    by_id = {item["question_id"]: item for item in questions}
    called_before = False
    for observation in runtime_questions:
        result = json.loads(json.dumps(observation["_result"]))
        result.setdefault("debug", {})["latency_ms"] = observation["latency_ms"]
        will_call = skip_reason(result, result.get("_gemini_facts")) is None
        if will_call and called_before:
            time.sleep(delay)
        called_before = called_before or will_call
        final = phrase_answer(result)
        debug = final["debug"]
        item = by_id[observation["question_id"]]
        tokens = debug.get("gemini_tokens") or {"input": 0, "output": 0, "total": 0}
        rows.append({"question_id": item["question_id"], "question": item["question"],
                     "status": final["status"], "gemini_status": debug.get("gemini_status"),
                     "served_by": debug.get("phrasing"), "tokens": tokens,
                     "gemini_latency_ms": debug.get("gemini_latency_ms", 0.0),
                     "end_to_end_latency_ms": debug.get("latency_ms"),
                     "deterministic_answer_correct": observation["answer_correct"],
                     "served_answer_correct": score_answer(item, final),
                     "served_citation_correct": score_citations(item, final, filenames),
                     "answer": final["answer"]})
    called = [row for row in rows if not str(row["gemini_status"]).startswith("skipped")]
    latencies = sorted(row["end_to_end_latency_ms"] for row in rows)
    return {
        "calls": len(called),
        "skipped": {status: sum(row["gemini_status"] == status for row in rows)
                    for status in sorted({row["gemini_status"] for row in rows
                                          if str(row["gemini_status"]).startswith("skipped")})},
        "accepted": sum(row["served_by"] == "gemini" for row in rows),
        "fallbacks": {status: sum(row["gemini_status"] == status for row in called)
                      for status in sorted({row["gemini_status"] for row in called if row["served_by"] != "gemini"})},
        "mean_input_tokens_per_call": statistics.mean(row["tokens"]["input"] for row in called) if called else 0,
        "mean_output_tokens_per_call": statistics.mean(row["tokens"]["output"] for row in called) if called else 0,
        "mean_total_tokens_per_call": statistics.mean(row["tokens"]["total"] for row in called) if called else 0,
        "mean_total_tokens_per_query": statistics.mean(row["tokens"]["total"] for row in rows),
        "mean_gemini_latency_ms_per_call": statistics.mean(row["gemini_latency_ms"] for row in called) if called else 0,
        "mean_end_to_end_latency_ms": statistics.mean(latencies),
        "p95_end_to_end_latency_ms": latencies[max(0, round(0.95 * len(latencies)) - 1)],
        "served_answer_accuracy": sum(row["served_answer_correct"] for row in rows) / len(rows),
        "questions": rows,
    }


def summarize(report):
    runtime = next(row for row in report["answers"] if (row["method"], row["chunk_strategy"]) == RUNTIME)
    answered = [q for q in runtime["questions"] if q["status"] == "answered"]
    removed = report["removed_evidence_abstention"]
    best = max(report["retrieval"], key=lambda row: (row["hit_rate"], row["mrr"]))
    summary = {
        "answer_accuracy": runtime["answer_accuracy"],
        "citation_accuracy": sum(q["citation_correct"] for q in answered) / len(answered) if answered else 0,
        "abstention_accuracy": (runtime["refusals_correct"] + removed["passed"])
                               / (runtime["refusals_total"] + removed["total"]),
        "false_refusal_rate": runtime["false_refusals"] / runtime["answerable_total"],
        "extraction_accuracy": report["extraction"]["accuracy"],
        "retrieval_hit_rate_best": best["hit_rate"],
        "retrieval_best_configuration": [best["method"], best["chunk_strategy"]],
        "deterministic_mean_latency_ms": runtime["mean_latency_ms"],
        "deterministic_p95_latency_ms": runtime["p95_latency_ms"],
    }
    if report.get("gemini"):
        gemini = report["gemini"]
        summary.update({"served_answer_accuracy": gemini["served_answer_accuracy"],
                        "served_mean_latency_ms": gemini["mean_end_to_end_latency_ms"],
                        "served_p95_latency_ms": gemini["p95_end_to_end_latency_ms"],
                        "mean_tokens_per_query": gemini["mean_total_tokens_per_query"]})
    return summary


def markdown(report):
    lines = [f"# Evaluation results ({report['generated_at']})", "",
             f"Manifest `{report['manifest_version']}`: {report['question_count']} questions "
             f"({report['answerable_count']} answerable, {report['question_count'] - report['answerable_count']} "
             "abstain/clarify). Offline run over freshly parsed PDFs; latency excludes Neon, network, and auth.", "",
             "## Retrieval (answerable questions, top 5)", "",
             "| Method | Chunking | Hits | Hit rate | MRR | Mean latency |", "|---|---|---|---|---|---|"]
    for row in report["retrieval"]:
        lines.append(f"| {row['method']} | {row['chunk_strategy']} | {row['hits']}/{row['question_count']} | "
                     f"{row['hit_rate']:.0%} | {row['mrr']:.3f} | {row['mean_latency_ms']:.1f} ms |")
    lines += ["", "## Deterministic answers", "",
              "| Method | Chunking | Correct | Answerable correct | Citations | False refusals | Refusals correct | Mean / p95 latency |",
              "|---|---|---|---|---|---|---|---|"]
    for row in report["answers"]:
        lines.append(f"| {row['method']} | {row['chunk_strategy']} | {row['answer_accuracy']:.0%} | "
                     f"{row['answerable_correct']}/{row['answerable_total']} | "
                     f"{row['citation_correct']}/{row['answerable_total']} | {row['false_refusals']} | "
                     f"{row['refusals_correct']}/{row['refusals_total']} | "
                     f"{row['mean_latency_ms']:.0f} / {row['p95_latency_ms']:.0f} ms |")
    removed = report["removed_evidence_abstention"]
    extraction = report["extraction"]
    lines += ["", f"Abstention when labeled source evidence is removed: {removed['passed']}/{removed['total']}.", "",
              "## Extraction", "",
              f"{extraction['correct']}/{extraction['total']} fields correct ({extraction['accuracy']:.0%}); "
              f"{extraction['incomplete']} missing network context, {extraction['wrong']} wrong, "
              f"{extraction['flagged']} flagged ambiguous, {extraction['missing']} missing.", ""]
    for field in extraction["fields"]:
        if field["outcome"] != "correct":
            lines.append(f"- {field['outcome']}: {field['source_document_id']} {field['field']} "
                         f"{field.get('service') or ''} {field['network'] or ''} {field['scope'] or ''} "
                         f"(expected {field['value']})".replace("  ", " "))
    if report.get("gemini"):
        gemini = report["gemini"]
        lines += ["", "## Gemini (runtime configuration)", "",
                  f"- Calls: {gemini['calls']} of {len(gemini['questions'])} queries; skipped by rule: {gemini['skipped']}; "
                  f"Gemini text served: {gemini['accepted']}; fallbacks: {gemini['fallbacks']}",
                  f"- Mean tokens per call: {gemini['mean_input_tokens_per_call']:.0f} input, "
                  f"{gemini['mean_output_tokens_per_call']:.0f} output, {gemini['mean_total_tokens_per_call']:.0f} total; "
                  f"per query (skipped = 0): {gemini['mean_total_tokens_per_query']:.0f}",
                  f"- Mean Gemini latency per call: {gemini['mean_gemini_latency_ms_per_call']:.0f} ms; end-to-end mean / p95: "
                  f"{gemini['mean_end_to_end_latency_ms']:.0f} / {gemini['p95_end_to_end_latency_ms']:.0f} ms",
                  f"- Served-answer accuracy: {gemini['served_answer_accuracy']:.0%}"]
    return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--gemini", action="store_true", help="call Gemini once per question (uses API quota)")
    parser.add_argument("--gemini-delay", type=float, default=4.5, help="seconds between Gemini calls")
    parser.add_argument("--output", type=Path, default=ROOT / "evaluation/results")
    args = parser.parse_args()
    load_dotenv(ROOT / ".env")

    manifest = json.loads((ROOT / "evaluation/questions.json").read_text())
    labels = json.loads((ROOT / "evaluation/extraction_labels.json").read_text())
    metadata = json.loads((SOURCE_DIR / "metadata.json").read_text())
    questions = manifest["questions"]
    corpus, ids = build_corpus(metadata)
    ids_by_sha = {document["sha256"]: ids[document["document_id"]] for document in metadata["documents"]}
    filenames = {document["document_id"]: document["original_filename"] for document in metadata["documents"]}
    answerable = [item for item in questions if item["expected_status"] == "answered"]

    retrieval.retrieve(corpus, "warm up", "semantic", "section_aware")
    answers = evaluate_answers(corpus, questions, ids, filenames)
    runtime = next(row for row in answers if (row["method"], row["chunk_strategy"]) == RUNTIME)
    report = {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "manifest_version": manifest["manifest_version"], "question_count": len(questions),
        "answerable_count": len(answerable), "runtime_configuration": list(RUNTIME),
        "embedding_model": retrieval.MODEL_NAME,
        "retrieval": evaluate_retrieval(corpus, answerable, ids_by_sha),
        "answers": answers,
        "removed_evidence_abstention": evaluate_removed_evidence(corpus, questions, ids),
        "extraction": evaluate_extraction(corpus, labels, ids),
    }
    if args.gemini:
        report["gemini"] = evaluate_gemini(runtime["questions"], questions, filenames, args.gemini_delay)
    report["summary"] = summarize(report)
    for row in answers:
        for question in row["questions"]:
            question.pop("_result", None)
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "latest.json").write_text(json.dumps(report, indent=2, default=str) + "\n")
    (args.output / "latest.md").write_text(markdown(report))
    print(markdown(report))


if __name__ == "__main__":
    main()
