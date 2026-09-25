"""Deterministic answers from reviewed benefits and approved source evidence."""

from __future__ import annotations

import os
import re
import time
from decimal import Decimal
from typing import Any

from app.retrieval import retrieve, tokenize

CATEGORIES = (
    ("out_of_pocket_maximum", re.compile(r"out[- ]of[- ]pocket|out of pocket|oop max", re.I)),
    ("er_cost_sharing", re.compile(r"emergency room|emergency department|\bER\b", re.I)),
    ("deductible", re.compile(r"deductib", re.I)),
    ("copay", re.compile(r"copay|co-pay|office visit", re.I)),
)
LABELS = {
    "deductible": "deductible",
    "er_cost_sharing": "emergency room cost sharing",
    "copay": "copay",
    "out_of_pocket_maximum": "out-of-pocket maximum",
}
VALUE = re.compile(r"\$\s?\d[\d,]*(?:\.\d{1,2})?|\b\d+(?:\.\d+)?\s?%|\bno charge\b|\bno deductible\b|\bnot covered\b", re.I)
COMPARISON = re.compile(r"\b(compare|comparison|difference|versus|vs\.?|between|across|both|higher|lower|more|less)\b", re.I)
STOP_WORDS = {"a", "about", "and", "are", "at", "be", "benefit", "benefits", "can", "cost", "cover", "covered", "coverage", "do", "does", "for", "how", "i", "in", "include", "included", "is", "it", "many", "me", "much", "my", "of", "on", "plan", "plans", "please", "service", "services", "tell", "the", "their", "this", "to", "under", "what", "whether", "which", "with"}
NAME_WORDS = {"plan", "plans", "summary", "benefit", "benefits", "coverage", "health", "insurance", "2017"}
SERVICE_NAMES = (
    ("specialist", re.compile(r"specialist", re.I)),
    ("primary care", re.compile(r"primary care|primary doctor|pcp", re.I)),
    ("urgent care", re.compile(r"urgent care", re.I)),
    ("prescription", re.compile(r"prescription|pharmacy|drug", re.I)),
    ("office visit", re.compile(r"office visit", re.I)),
)


def _fold(value: str) -> str:
    return " ".join(tokenize(value))


def _display(plan: dict) -> str:
    return f"{plan['insurer']} {plan['plan_name']}".strip()


def _matches(question: str, plans: list[dict]) -> list[dict]:
    normalized = f" {_fold(question)} "
    strong: list[dict] = []
    insurer_only: list[dict] = []
    for plan in plans:
        insurer_words = set(tokenize(plan["insurer"]))
        plan_words = tokenize(plan["plan_name"])
        distinctive = [word for word in plan_words if word not in NAME_WORDS]
        name = " ".join(distinctive)
        insurer = _fold(plan["insurer"])
        full = _fold(_display(plan))
        type_alias = _fold(plan.get("plan_type") or "")
        coverage_alias = _fold(plan.get("coverage_type") or "")
        acronym_words = [word for word in plan_words
                         if word not in NAME_WORDS and word not in insurer_words
                         and word not in {type_alias, coverage_alias}]
        acronym = "".join(word[0] for word in acronym_words) if len(acronym_words) >= 2 else ""
        qualified_insurer = bool(insurer and f" {insurer} " in normalized and (
            (type_alias not in {"", "unknown", "other"} and f" {type_alias} " in normalized) or
            (coverage_alias not in {"", "unknown", "medical"} and f" {coverage_alias} " in normalized)
        ))
        if ((name and f" {name} " in normalized) or (full and f" {full} " in normalized)
                or (acronym and f" {acronym} " in normalized) or qualified_insurer):
            strong.append(plan)
        elif insurer and f" {insurer} " in normalized:
            insurer_only.append(plan)
    strong_insurers = {_fold(plan["insurer"]) for plan in strong}
    return strong + [plan for plan in insurer_only if _fold(plan["insurer"]) not in strong_insurers]


def _category(question: str) -> str | None:
    return next((name for name, pattern in CATEGORIES if pattern.search(question)), None)


def _qualifiers(question: str) -> dict[str, str]:
    result = {}
    if re.search(r"out[- ]of[- ]network", question, re.I):
        result["network"] = "out"
    elif re.search(r"in[- ]network", question, re.I):
        result["network"] = "in"
    if re.search(r"\bfamily\b", question, re.I):
        result["scope"] = "family"
    elif re.search(r"\bindividual\b|per person", question, re.I):
        result["scope"] = "individual"
    return result


def _dimensions(record: dict) -> tuple[str, str, str]:
    dimensions = record.get("dimensions") or {}
    wording = str(record.get("value_text") or "")
    network = str(dimensions.get("network") or "").lower()
    scope = " ".join(str(dimensions.get(key) or "") for key in ("family", "individual")).lower()
    if not network:
        network = wording.lower()
    if not scope:
        scope = wording.lower()
    network_key = "out" if re.search(r"out[- ]of[- ]network", network) else "in" if re.search(r"in[- ]network", network) else "unspecified"
    scope_key = "family" if "family" in scope else "individual" if re.search(r"individual|per person", scope) else "unspecified"
    service_text = " ".join(str(dimensions.get(key) or "") for key in ("service", "visit_type")) or wording
    service = next((name for name, pattern in SERVICE_NAMES if pattern.search(service_text)), "unspecified")
    return network_key, scope_key, service


def _value(record: dict) -> str | None:
    wording = str(record.get("value_text") or "")
    values = {re.sub(r"\s+", "", match.group(0)).lower() for match in VALUE.finditer(wording)}
    if len(values) != 1:
        return None
    return next(iter(values))


def _ordered_value(value: str) -> tuple[str, Decimal] | None:
    if value.startswith("$"):
        return "dollars", Decimal(value[1:].replace(",", ""))
    if value.endswith("%"):
        return "percent", Decimal(value[:-1])
    if value in {"nocharge", "nodeductible"}:
        return "dollars", Decimal(0)
    return None


def _citation(record: dict) -> dict:
    return {"plan": record["plan_name"], "section": record["section"],
            "page": record.get("page_number"), "document": record["original_filename"]}


def _response(status: str, answer: str, plans: list[dict], path: str, started: float,
              citations: list[dict] | None = None, details: dict | None = None,
              admin: bool = False) -> dict:
    debug: dict[str, Any] = {
        "evidence_path": path,
        "corpus": "approved provisional documents; SBC/public-source status unverified",
        "latency_ms": round((time.perf_counter() - started) * 1000, 1),
    }
    if admin:
        debug.update(details or {})
    return {"status": status, "answer": answer, "citations": citations or [],
            "matched_plans": [_display(plan) for plan in plans],
            "context_plan_ids": [plan["plan_id"] for plan in plans], "debug": debug}


def _approved_plans(connection) -> list[dict]:
    rows = connection.execute(
        """SELECT DISTINCT p.plan_id, p.insurer, p.plan_name, p.plan_type, p.coverage_type, p.plan_year
           FROM plans p JOIN documents d USING (plan_id)
           WHERE d.review_status = 'approved' AND d.corpus_status <> 'ineligible'
           ORDER BY p.insurer, p.plan_name, p.plan_id"""
    ).fetchall()
    return [dict(row) for row in rows]


def _benefits(connection, plan_ids: list[int], category: str) -> list[dict]:
    rows = connection.execute(
        """SELECT b.benefit_id, b.plan_id, b.category, b.value_text, b.dimensions,
                  b.verification_status, b.reviewed_at, b.source_section,
                  b.source_section_verified,
                  pg.page_number, pg.parse_status,
                  NULLIF(b.source_section, '') AS section,
                  d.document_id, d.original_filename, p.plan_name
           FROM benefit_records b JOIN documents d USING (document_id)
           JOIN plans p ON p.plan_id = b.plan_id
           LEFT JOIN document_pages pg ON pg.page_id = b.source_page_id AND pg.document_id = b.document_id
           WHERE b.plan_id = ANY(%s) AND b.category = %s
             AND d.review_status = 'approved' AND d.corpus_status <> 'ineligible'
           ORDER BY b.plan_id, b.benefit_id""", (plan_ids, category)
    ).fetchall()
    return [dict(row) for row in rows]


def _numeric_answer(connection, question: str, plans: list[dict], category: str, started: float,
                    admin: bool) -> dict:
    rows = _benefits(connection, [plan["plan_id"] for plan in plans], category)
    requested = _qualifiers(question)
    requested_service = next((name for name, pattern in SERVICE_NAMES if pattern.search(question)), None) if category == "copay" else None
    selected = []
    reasons = []
    for plan in plans:
        plan_candidates = [row for row in rows if row["plan_id"] == plan["plan_id"]]
        candidates = plan_candidates
        if requested:
            candidates = [row for row in candidates if all(
                (key == "network" and _dimensions(row)[0] == wanted) or
                (key == "scope" and _dimensions(row)[1] == wanted)
                for key, wanted in requested.items())]
        if requested_service:
            candidates = [row for row in candidates if _dimensions(row)[2] == requested_service]
        verified = [row for row in candidates if row["verification_status"] == "verified"]
        if any(row["verification_status"] == "conflicting" for row in candidates):
            reasons.append(f"{_display(plan)} has conflicting reviewed values")
        elif any(
                row["verification_status"] in {"pending_review", "ambiguous"}
                and all(
                    key not in requested or _dimensions(row)[index] in {wanted, "unspecified"}
                    for key, wanted, index in (("network", requested.get("network"), 0),
                                               ("scope", requested.get("scope"), 1))
                    if wanted is not None
                )
                and (not requested_service or _dimensions(row)[2] in {requested_service, "unspecified"})
                for row in plan_candidates):
            reasons.append(f"{_display(plan)} has unresolved benefit candidates for this question")
        elif not verified:
            reasons.append(f"{_display(plan)} has no verified value for this question")
        elif any(not row["section"] or not row["source_section_verified"]
                 or not _value(row) or not row["reviewed_at"]
                 or (row["parse_status"] is not None and row["parse_status"] != "parsed")
                 for row in verified):
            reasons.append(f"{_display(plan)} lacks an unambiguous reviewed value or usable source provenance")
        else:
            signatures = {(_dimensions(row), _value(row)) for row in verified}
            if len(signatures) > 1:
                dimensions = {_dimensions(row) for row in verified}
                reasons.append(f"{_display(plan)} has {'multiple benefit contexts' if len(dimensions) > 1 else 'conflicting verified values'}")
            else:
                selected.append(verified[0])
    if reasons:
        status = "clarification_needed" if all("multiple benefit contexts" in reason for reason in reasons) else "insufficient_evidence"
        answer = ("Please specify the network, individual or family context, and service where relevant. "
                  if status == "clarification_needed" else "I can’t establish the requested value from approved, reviewed evidence. ")
        answer += " ".join(reasons) + "."
        return _response(status, answer, plans, "verified_structured_benefits", started,
                         details={"evidence_gate": reasons, "candidate_count": len(rows)}, admin=admin)
    if len(selected) > 1 and len({_dimensions(row) for row in selected}) > 1:
        return _response("clarification_needed", "The reviewed values use different network, individual/family, or service contexts. Specify a common context to compare.",
                         plans, "verified_structured_benefits", started,
                         details={"evidence_gate": "incomparable_dimensions"}, admin=admin)
    citations = [_citation(row) for row in selected]
    lines = [f"{row['plan_name']}: {row['value_text']}" for row in selected]
    direction = re.search(r"\b(lower|less|higher|more)\b", question, re.I) if len(selected) > 1 else None
    comparison_text = ""
    if direction:
        amounts = [_ordered_value(_value(row)) for row in selected]
        if any(amount is None for amount in amounts) or len({amount[0] for amount in amounts}) != 1:
            return _response("clarification_needed", "The reviewed values use different or nonnumeric units, so I can’t order them reliably.",
                             plans, "verified_structured_benefits", started, admin=admin)
        lowest = direction.group(1).lower() in {"lower", "less"}
        target = (min if lowest else max)(amount[1] for amount in amounts)
        winners = [row["plan_name"] for row, amount in zip(selected, amounts) if amount[1] == target]
        comparison_text = (f"{', '.join(winners)} {'tie for the' if len(winners) > 1 else 'has the'} "
                           f"{'lowest' if lowest else 'highest'} reviewed {LABELS[category]}. ")
    answer = (comparison_text + f"Reviewed {LABELS[category]} source wording: " + " ".join(lines) +
              " These are from approved provisional documents; their SBC and public-source status is unverified.")
    return _response("answered", answer, plans, "verified_structured_benefits", started, citations,
                     details={"benefit_ids": [row["benefit_id"] for row in selected],
                              "document_ids": [row["document_id"] for row in selected]}, admin=admin)


def _source_unit(chunk: dict, terms: set[str]) -> tuple[int, dict] | None:
    best = None
    plan_name = _fold(str(chunk.get("plan_name") or ""))
    for unit in (chunk.get("provenance") or {}).get("units", []):
        if unit.get("kind") == "table_row":
            headers = [str(value) for value in unit.get("headers") or []]
            cells = [str(value) for value in unit.get("cells") or []]
            wording = " | ".join(f"{headers[index] if index < len(headers) else 'Column'}: {cell}"
                                 for index, cell in enumerate(cells) if cell)
            section = " | ".join(header for header in headers if header) or unit.get("section")
        else:
            wording = str(unit.get("line") or "")
            section = unit.get("section")
        unit_terms = set(tokenize(wording))
        overlap = len(terms & unit_terms)
        if not section or not wording or overlap < len(terms):
            continue
        folded_section = _fold(str(section))
        section_terms = set(tokenize(folded_section))
        plan_terms = set(tokenize(plan_name)) - NAME_WORDS
        document_title = (
            folded_section in {"plan title", "plan summary", "summary of benefits and coverage"}
            or ("summary" in section_terms and bool(section_terms & {"benefits", "coverage", "plan"}))
            or folded_section.endswith(" plan")
        )
        if document_title or (
                plan_terms and plan_terms.issubset(section_terms)):
            continue
        if not re.search(r"\b(covered|coverage|not covered|no charge|copay|coinsurance|deductible|limit|visit|per year)\b|\$|%", wording, re.I):
            continue
        candidate = {"plan_name": chunk["plan_name"], "original_filename": chunk["original_filename"],
                     "section": str(section)[:240], "page_number": unit.get("page"),
                     "wording": wording, "chunk_id": chunk["chunk_id"], "rank": chunk["rank"],
                     "score": chunk["score"], "kind": unit.get("kind")}
        if best is None or (overlap, unit.get("kind") == "table_row") > (
                best[0], best[1]["kind"] == "table_row"):
            best = (overlap, candidate)
    return best


def _coverage_answer(connection, question: str, plans: list[dict], all_plans: list[dict],
                     started: float, admin: bool, method_override: str | None = None,
                     strategy_override: str | None = None) -> dict:
    excluded = set().union(*(set(tokenize(_display(plan))) for plan in all_plans))
    terms = set(tokenize(question)) - STOP_WORDS - excluded
    terms -= {"compare", "comparison", "difference", "versus", "vs", "between", "across", "both", "higher", "lower", "more", "less"}
    if not terms or len(terms) > 4:
        return _response("clarification_needed", "Which specific service or coverage item should I look for?", plans,
                         "retrieved_source", started, admin=admin)
    method = method_override or os.getenv("ANSWER_RETRIEVAL_METHOD", "bm25")
    strategy = strategy_override or os.getenv("ANSWER_CHUNK_STRATEGY", "section_aware")
    if method not in {"bm25", "semantic"} or strategy not in {"fixed_size", "section_aware"}:
        raise ValueError("ANSWER_RETRIEVAL_METHOD or ANSWER_CHUNK_STRATEGY is invalid")
    chosen = []
    traces = []
    for plan in plans:
        result = retrieve(connection, " ".join(sorted(terms)), method, strategy, top_k=10, plan_id=plan["plan_id"])
        traces.append({"plan_id": plan["plan_id"], "index_status": result.get("index_status"),
                       "timings": result["timings"],
                       "ranks": [{"chunk_id": row["chunk_id"], "rank": row["rank"], "score": row["score"]}
                                 for row in result["results"]]})
        candidates = [_source_unit(row, terms) for row in result["results"]]
        candidates = [item for item in candidates if item]
        if not candidates:
            return _response("insufficient_evidence", "I can’t establish that coverage from a traceable source row in every requested approved document.",
                             plans, "retrieved_source", started,
                             details={"retrieval_method": method, "chunk_strategy": strategy, "retrieval": traces}, admin=admin)
        table_pages = {item[1]["page_number"] for item in candidates if item[1]["kind"] == "table_row"}
        candidates = [item for item in candidates
                      if item[1]["kind"] == "table_row" or item[1]["page_number"] not in table_pages]
        distinct_wording = {_fold(item[1]["wording"]) for item in candidates}
        if len(distinct_wording) > 1:
            return _response("clarification_needed", "Several source rows match that service with different wording. Specify a narrower service or network context.",
                             plans, "retrieved_source", started,
                             details={"retrieval_method": method, "chunk_strategy": strategy, "retrieval": traces,
                                      "matching_chunk_ids": [item[1]["chunk_id"] for item in candidates]}, admin=admin)
        chosen.append(max(candidates, key=lambda item: (item[0], -item[1]["rank"]))[1])
    citations = [_citation(row) for row in chosen]
    answer = "Source wording from approved provisional documents: " + " ".join(
        f"{row['plan_name']}: “{row['wording']}”" for row in chosen)
    answer += " Their SBC and public-source status is unverified."
    return _response("answered", answer, plans, "retrieved_source", started, citations,
                     details={"retrieval_method": method, "chunk_strategy": strategy, "retrieval": traces,
                              "evidence_chunk_ids": [row["chunk_id"] for row in chosen]}, admin=admin)


def answer_question(connection, question: str, context_plan_ids: list[int] | None = None,
                    previous_question: str | None = None, admin: bool = False,
                    method_override: str | None = None, strategy_override: str | None = None) -> dict:
    started = time.perf_counter()
    plans = _approved_plans(connection)
    if not plans:
        return _response("insufficient_evidence", "No reviewed, approved plan documents are available yet.", [],
                         "no_approved_documents", started, admin=admin)
    explicit = _matches(question, plans)
    comparison = bool(COMPARISON.search(question)) or bool(
        not explicit and context_plan_ids and len(context_plan_ids) > 1 and previous_question
        and COMPARISON.search(previous_question) and len(question.split()) <= 8
    )
    if explicit:
        selected = explicit
    elif comparison and context_plan_ids and not re.search(r"\b(?:all|across all)\b", question, re.I):
        selected = [plan for plan in plans if plan["plan_id"] in context_plan_ids]
    elif comparison:
        selected = plans
    elif context_plan_ids:
        selected = [plan for plan in plans if plan["plan_id"] in context_plan_ids]
    elif len(plans) == 1:
        selected = plans
    else:
        selected = []
    requested_coverages = {coverage for coverage in ("medical", "dental", "vision")
                           if re.search(rf"\b{coverage}\b", question, re.I)}
    if comparison and not explicit and len(requested_coverages) == 1:
        selected = [plan for plan in selected if plan["coverage_type"] in requested_coverages]
    if not selected:
        return _response("clarification_needed", "Which plan do you mean? Available approved plans: " +
                         "; ".join(_display(plan) for plan in plans) + ".", [], "plan_resolution", started,
                         details={"available_plan_ids": [plan["plan_id"] for plan in plans]}, admin=admin)
    if len(selected) > 1 and not comparison:
        return _response("clarification_needed", "Please name one plan, or ask to compare these plans: " +
                         "; ".join(_display(plan) for plan in selected) + ".", [], "plan_resolution", started,
                         details={"candidate_plan_ids": [plan["plan_id"] for plan in selected]}, admin=admin)
    if comparison and len(selected) < 2:
        return _response("clarification_needed", "Name at least two plans to compare, or ask to compare across all approved plans.",
                         selected, "plan_resolution", started, admin=admin)
    if comparison and len({plan["coverage_type"] for plan in selected}) > 1:
        return _response("clarification_needed", "These plans have different coverage types (medical, dental, or vision). Name plans with the same coverage type to compare.",
                         selected, "plan_resolution", started, admin=admin)
    category = _category(question)
    followup = bool(re.match(r"^(what about|how about|and\b|for\b)", question.strip(), re.I)) or not re.match(
        r"^(what|how|does|do|is|are|can|which|compare|tell)\b", question.strip(), re.I)
    if not category and previous_question and len(question.split()) <= 8 and (followup or COMPARISON.search(question)):
        category = _category(previous_question)
        question = previous_question + " " + question
    if category:
        return _numeric_answer(connection, question, selected, category, started, admin)
    return _coverage_answer(connection, question, selected, plans, started, admin,
                            method_override, strategy_override)
