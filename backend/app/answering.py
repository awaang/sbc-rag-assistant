"""Deterministic answers from ready, traceable source evidence."""

from __future__ import annotations

import os
import re
import time
from decimal import Decimal
from typing import Any

from app.retrieval import approved_chunks, retrieve, tokenize

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
NONE_DEDUCTIBLE = re.compile(r"\b(?:plan|drug)?\s*deductible\s*:\s*none\b", re.I)
COMPARISON = re.compile(r"\b(compare|comparison|difference|versus|vs\.?|between|across|both|higher|lower|more|less)\b", re.I)
STOP_WORDS = {"a", "about", "amount", "and", "are", "at", "available", "be", "benefit", "benefits", "can", "cost", "cover", "covered", "coverage", "dental", "do", "does", "during", "for", "how", "i", "in", "include", "included", "including", "is", "it", "list", "listed", "many", "me", "medical", "member", "much", "my", "of", "on", "pay", "pays", "plan", "plans", "please", "say", "says", "service", "services", "tell", "the", "their", "this", "to", "under", "vision", "what", "whether", "which", "with"}
NAME_WORDS = {"plan", "plans", "summary", "benefit", "benefits", "coverage", "health", "insurance", "2017"}
GENERIC_INSURER_WORDS = {"group", "the", "first", "united"}
SERVICE_NAMES = (
    ("specialist", re.compile(r"specialist", re.I)),
    ("primary care", re.compile(r"primary care|primary doctor|pcp", re.I)),
    ("urgent care", re.compile(r"urgent care", re.I)),
    ("prescription", re.compile(r"prescription|pharmacy|drug", re.I)),
    ("office visit", re.compile(r"office visit", re.I)),
)


def _fold(value: str) -> str:
    return " ".join(tokenize(value))


def _search_terms(value: str) -> set[str]:
    """Normalize common written forms while keeping evidence matching lexical."""
    normalized = re.sub(r"\bx[\s-]+rays?\b", "xray", value, flags=re.I)
    return set(tokenize(normalized))


def _display(plan: dict) -> str:
    insurer = str(plan["insurer"]).strip()
    name = str(plan["plan_name"]).strip()
    return name if name.lower().startswith(insurer.lower() + " ") else f"{insurer} {name}".strip()


def _brand(insurer: str) -> str:
    """Short insurer name users type, e.g. "aetna" for "Aetna Life Insurance Company"."""
    words = tokenize(insurer)
    return " ".join(words[:2] if len(words) > 1 and words[0] in GENERIC_INSURER_WORDS else words[:1])


def _matches(question: str, plans: list[dict]) -> list[dict]:
    normalized = f" {_fold(question)} "
    strong: list[dict] = []
    insurer_only: list[dict] = []
    for plan in plans:
        insurer_words = set(tokenize(plan["insurer"]))
        plan_words = tokenize(plan["plan_name"])
        distinctive = [word for word in plan_words if word not in NAME_WORDS]
        name = " ".join(distinctive)
        full_insurer = _fold(plan["insurer"])
        insurer = _brand(plan["insurer"]) if f" {full_insurer} " not in normalized else full_insurer
        full = _fold(_display(plan))
        type_alias = _fold(plan.get("plan_type") or "")
        coverage_alias = _fold(plan.get("coverage_type") or "")
        acronym_words = [word for word in plan_words
                         if word not in NAME_WORDS and word not in insurer_words
                         and word not in {type_alias, coverage_alias}]
        acronym = "".join(word[0] for word in acronym_words) if len(acronym_words) >= 2 else ""
        distinctive_aliases = [word for word in acronym_words if len(word) >= 3 and not any(
            other["plan_id"] != plan["plan_id"] and _brand(other["insurer"]) == _brand(plan["insurer"])
            and word in tokenize(other["plan_name"]) for other in plans)]
        product_alias = bool(coverage_alias == "vision" and " vsp " in normalized and
                             insurer and f" {insurer} " in normalized)
        qualified_insurer = bool(insurer and f" {insurer} " in normalized and (
            (type_alias not in {"", "unknown", "other"} and f" {type_alias} " in normalized) or
            (coverage_alias not in {"", "unknown", "medical"} and f" {coverage_alias} " in normalized)
        ))
        if ((name and f" {name} " in normalized) or (full and f" {full} " in normalized)
                or (insurer and f" {insurer} " in normalized and
                    any(f" {word} " in normalized for word in distinctive_aliases))
                or (acronym and f" {acronym} " in normalized) or qualified_insurer or product_alias):
            strong.append(plan)
        elif insurer and f" {insurer} " in normalized:
            insurer_only.append(plan)
    strong_insurers = {_brand(plan["insurer"]) for plan in strong}
    return strong + [plan for plan in insurer_only if _brand(plan["insurer"]) not in strong_insurers]


def _category(question: str) -> str | None:
    return next((name for name, pattern in CATEGORIES if pattern.search(question)), None)


def _bare_deductible_request(question: str) -> bool:
    return bool(re.fullmatch(
        r"(?:what(?: is|'s) (?:the |my )?|how much is (?:the |my )?)deductible\s*\??",
        question.strip(), re.I))


def _qualifiers(question: str) -> dict[str, str]:
    result = {}
    if re.search(r"out[- ]of[- ]network", question, re.I):
        result["network"] = "out"
    elif re.search(r"in[- ]network", question, re.I):
        result["network"] = "in"
    if re.search(r"\bfamily\b", question, re.I):
        result["scope"] = "family"
    elif re.search(r"\bindividual\b|per person|self[- ]only", question, re.I):
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
    service_text = " ".join(str(dimensions.get(key) or "") for key in ("service", "visit_type")).strip() or wording
    service = next((name for name, pattern in SERVICE_NAMES if pattern.search(service_text)), "unspecified")
    return network_key, scope_key, service


def _value(record: dict) -> str | None:
    wording = str(record.get("value_text") or "")
    values = {re.sub(r"\s+", "", match.group(0)).lower() for match in VALUE.finditer(wording)}
    if record.get("category") == "deductible" and NONE_DEDUCTIBLE.search(wording):
        values.add("none")
    if len(values) != 1:
        return None
    return next(iter(values))


def _usable_section(record: dict) -> bool:
    section = _fold(str(record.get("section") or ""))
    plan = _fold(str(record.get("plan_name") or ""))
    if not section or section in {"plan title", "plan summary", "summary of benefits and coverage",
                                  "plan design benefits", "employees", plan}:
        return False
    return not (section.endswith(" plan") and not any(
        term in section for term in ("cost", "benefit", "coverage", "deductible")))


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
        "corpus": "queryable ready SBC documents",
        "latency_ms": round((time.perf_counter() - started) * 1000, 1),
    }
    if admin:
        debug.update(details or {})
    return {"status": status, "answer": answer, "citations": citations or [],
            "matched_plans": [_display(plan) for plan in plans],
            "context_plan_ids": [plan["plan_id"] for plan in plans], "debug": debug}


YEAR = re.compile(r"(?<![$\d,.])\b(?:19|20)\d{2}\b")


def _unsupported_year(question: str, plans: list[dict]) -> str | None:
    """Explain why a question about a specific year can't use these plan documents."""
    asked = set(YEAR.findall(question)) - {year for plan in plans for year in YEAR.findall(_display(plan))}
    if not asked:
        return None
    mismatched = [plan for plan in plans if str(plan.get("plan_year") or "") not in asked]
    if not mismatched:
        return None
    years = ", ".join(sorted(asked))
    reasons = "; ".join(f"{_display(plan)} covers plan year {plan['plan_year']}" if plan.get("plan_year")
                        else f"{_display(plan)} has no recorded plan year" for plan in mismatched)
    return f"I can’t establish {years} values from the available documents: {reasons}."


def _approved_plans(connection) -> list[dict]:
    rows = connection.execute(
        """SELECT DISTINCT p.plan_id, p.insurer, p.plan_name, p.plan_type, p.coverage_type, p.plan_year
           FROM plans p JOIN documents d USING (plan_id)
           WHERE d.review_status IN ('approved', 'ready', 'ready_with_warnings') AND d.corpus_status <> 'ineligible'
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
             AND d.review_status IN ('approved', 'ready', 'ready_with_warnings') AND d.corpus_status <> 'ineligible'
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
        if category == "deductible":
            drug_requested = bool(re.search(r"\b(?:drug|prescription|pharmacy)\b", question, re.I))
            plan_candidates = [row for row in plan_candidates
                               if re.match(r"\s*(?:(?:in[- ]network|out[- ]of[- ]network)\s+)?"
                                           r"(?:(?:individual|family)\s+)?(?:plan |drug )?deductible\b",
                                           row["value_text"], re.I)
                               and bool(re.search(r"\bdrug deductible\b", row["value_text"], re.I))
                               == drug_requested]
        candidates = plan_candidates
        if requested:
            candidates = [row for row in candidates if all(
                (key == "network" and _dimensions(row)[0] == wanted) or
                (key == "scope" and _dimensions(row)[1] == wanted)
                for key, wanted in requested.items())]
        if requested_service:
            candidates = [row for row in candidates if _dimensions(row)[2] == requested_service]
        relevant = [row for row in plan_candidates if all(
            key not in requested or _dimensions(row)[index] in {wanted, "unspecified"}
            for key, wanted, index in (("network", requested.get("network"), 0),
                                       ("scope", requested.get("scope"), 1)) if wanted is not None
        ) and (not requested_service or _dimensions(row)[2] == requested_service or
               (_dimensions(row)[2] == "unspecified" and
                next(pattern for name, pattern in SERVICE_NAMES if name == requested_service).search(
                    str(row.get("value_text") or "") + " " + str(row.get("section") or ""))))]
        usable = [row for row in candidates if row["verification_status"] in {"verified", "pending_review"}]
        if any(row["verification_status"] in {"conflicting", "ambiguous"} for row in relevant):
            reasons.append(f"{_display(plan)} has ambiguous or conflicting values for this question")
        elif any(row not in candidates and row["verification_status"] in {"verified", "pending_review"}
                 and _value(row) and any(_value(row) != _value(chosen) for chosen in candidates)
                 for row in relevant):
            reasons.append(f"{_display(plan)} has conflicting values with unspecified context")
        elif any(row["verification_status"] in {"verified", "pending_review"} and (
                not _usable_section(row) or not row.get("page_number") or not _value(row)
                or row.get("parse_status") != "parsed"
                or (row["verification_status"] == "verified" and
                    (not row.get("source_section_verified") or not row.get("reviewed_at"))))
                for row in relevant):
            reasons.append(f"{_display(plan)} lacks an unambiguous value or usable source provenance")
        elif not usable:
            reasons.append(f"{_display(plan)} has no supported value for this question")
        else:
            signatures = {(_dimensions(row), _value(row)) for row in usable}
            if len(signatures) > 1:
                dimensions = {_dimensions(row) for row in usable}
                reasons.append(f"{_display(plan)} has {'multiple benefit contexts' if len(dimensions) > 1 else 'conflicting values'}")
            else:
                selected.append(next((row for row in usable if row["verification_status"] == "verified"), usable[0]))
    if reasons:
        status = "clarification_needed" if all("multiple benefit contexts" in reason for reason in reasons) else "insufficient_evidence"
        answer = ("Please specify the network, individual or family context, and service where relevant. "
                  if status == "clarification_needed" else "I can’t establish the requested value from traceable evidence. ")
        answer += " ".join(reasons) + "."
        return _response(status, answer, plans, "structured_benefits", started,
                         details={"evidence_gate": reasons, "candidate_count": len(rows)}, admin=admin)
    if len(selected) > 1 and len({_dimensions(row) for row in selected}) > 1:
        return _response("clarification_needed", "The reviewed values use different network, individual/family, or service contexts. Specify a common context to compare.",
                         plans, "structured_benefits", started,
                         details={"evidence_gate": "incomparable_dimensions"}, admin=admin)
    citations = [_citation(row) for row in selected]
    lines = [f"{row['plan_name']}: {row['value_text']}" for row in selected]
    direction = re.search(r"\b(lower|less|higher|more)\b", question, re.I) if len(selected) > 1 else None
    comparison_text = ""
    if direction:
        amounts = [_ordered_value(_value(row)) for row in selected]
        if any(amount is None for amount in amounts) or len({amount[0] for amount in amounts}) != 1:
            return _response("clarification_needed", "The values use different or nonnumeric units, so I can’t order them reliably.",
                             plans, "structured_benefits", started, admin=admin)
        lowest = direction.group(1).lower() in {"lower", "less"}
        target = (min if lowest else max)(amount[1] for amount in amounts)
        winners = [row["plan_name"] for row, amount in zip(selected, amounts) if amount[1] == target]
        comparison_text = (f"{', '.join(winners)} {'tie for the' if len(winners) > 1 else 'has the'} "
                           f"{'lowest' if lowest else 'highest'} {LABELS[category]}. ")
    answer = comparison_text + f"{LABELS[category].capitalize()} source wording: " + " ".join(lines)
    result = _response("answered", answer, plans, "structured_benefits", started, citations,
                       details={"benefit_ids": [row["benefit_id"] for row in selected],
                                "document_ids": [row["document_id"] for row in selected]}, admin=admin)
    result["_gemini_facts"] = {
        "kind": "numeric",
        "category": LABELS[category],
        "comparison": comparison_text,
        "facts": [{"plan": row["plan_name"], "value": row["value_text"]} for row in selected],
    }
    return result


def _multi_numeric_answer(connection, question: str, plans: list[dict], started: float,
                          admin: bool) -> dict | None:
    categories = [name for name, pattern in CATEGORIES if pattern.search(question)]
    if "er_cost_sharing" in categories:
        categories = [name for name in categories if name != "copay"]
    has_individual = bool(re.search(r"\bindividual\b|per person|self[- ]only", question, re.I))
    has_family = bool(re.search(r"\bfamily\b", question, re.I))
    scopes = [scope for scope, present in (("individual", has_individual), ("family", has_family)) if present]
    has_out = bool(re.search(r"out[- ]of[- ]network", question, re.I))
    has_in = bool(re.search(r"(?<!out[- ])in[- ]network", question, re.I))
    networks = [network for network, present in (("in-network", has_in), ("out-of-network", has_out)) if present]
    if len(categories) * max(1, len(scopes)) * max(1, len(networks)) <= 1:
        return None
    results = []
    for category in categories:
        for network in networks or [""]:
            for scope in scopes or [""]:
                subquery = " ".join(part for part in (network, scope, LABELS[category]) if part)
                result = _numeric_answer(connection, subquery, plans, category, started, admin)
                if result["status"] != "answered":
                    return _response(result["status"], result["answer"], plans,
                                     "structured_benefits", started,
                                     details={"evidence_gate": "multi_part_missing", "failed_context": subquery},
                                     admin=admin)
                results.append((subquery, result))
    citations = list({(citation["document"], citation["page"], citation["section"], citation["plan"]): citation
                      for _, result in results for citation in result["citations"]}.values())
    facts = [{"plan": fact["plan"], "value": f"{subquery.replace('-', ' ')}: {fact['value']}"}
             for subquery, result in results for fact in result["_gemini_facts"]["facts"]]
    answer = "Source wording: " + " ".join(f"{fact['plan']}: {fact['value']}." for fact in facts)
    combined = _response("answered", answer, plans, "structured_benefits", started, citations,
                         details={"contexts": [subquery for subquery, _ in results]}, admin=admin)
    combined["_gemini_facts"] = {"kind": "numeric", "facts": facts}
    return combined


def _source_unit(chunk: dict, terms: set[str]) -> tuple[int, dict] | None:
    best = None
    plan_name = _fold(str(chunk.get("plan_name") or ""))
    for unit in (chunk.get("provenance") or {}).get("units", []):
        if unit.get("kind") == "raw_line":
            continue
        if unit.get("kind") == "table_row":
            headers = [str(value) for value in unit.get("headers") or []]
            cells = [str(value) for value in unit.get("cells") or []]
            row_label = next((cell for cell in cells if cell and
                              not re.search(r"\$|\d+\s?%|\b(?:copay applies|covered|not covered|amount over)\b",
                                            cell, re.I)), "")
            wording = " | ".join(f"{headers[index] if index < len(headers) else 'Column'}: {cell}"
                                 for index, cell in enumerate(cells) if cell)
            detected_section = unit.get("section")
            section = (detected_section if detected_section and _usable_section({"section": detected_section,
                                                                                 "plan_name": chunk.get("plan_name")})
                       else row_label or " | ".join(header for header in headers if header))
        else:
            wording = str(unit.get("text") or "")
            section = unit.get("section")
        # Include the detected section: questions may name a benefit category
        # (for example, hospitalization) that appears in the heading rather
        # than the source row itself. Keep the cited wording limited to the row.
        unit_terms = _search_terms(f"{section} {wording}")
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
        if not re.search(r"\b(covered|coverage|not covered|no charge|copay|coinsurance|deductible|limit|visit|per year|cost share|supply|allowance|discount|not applicable)\b|\$|%", wording, re.I):
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
    from app.source_catalog import build_catalog, select_passages, project_passage, terms

    method = method_override or os.getenv("ANSWER_RETRIEVAL_METHOD", "bm25")
    strategy = strategy_override or os.getenv("ANSWER_CHUNK_STRATEGY", "section_aware")
    if method not in {"bm25", "semantic", "hybrid"} or strategy not in {"fixed_size", "section_aware"}:
        raise ValueError("ANSWER_RETRIEVAL_METHOD or ANSWER_CHUNK_STRATEGY is invalid")
    chosen, traces = [], []
    names = [value for plan in all_plans for value in
             (_display(plan), plan["plan_name"], plan["insurer"], _brand(plan["insurer"]))]
    names += [f"{_brand(plan['insurer'])} {plan['coverage_type']}" for plan in all_plans
              if plan["coverage_type"] in {"dental", "vision"}]
    for plan in plans:
        ranked = retrieve(connection, question + " " + " ".join(sorted(terms(question))),
                          method, strategy, top_k=50, plan_id=plan["plan_id"],
                          include_source_context=True)
        chunks = ranked.get("source_chunks", ranked["results"])
        cards = build_catalog(chunks)
        identity_names = []
        for chunk in chunks:
            for unit in (chunk.get("provenance") or {}).get("units", []):
                text = " ".join(unit.get("cells", [])) if unit.get("kind") == "table_row" else unit.get("text", "")
                if unit.get("page") == 1 and len(text) < 120 and re.search(r"\b(?:HMO|POS|PPO)\b", text) and not VALUE.search(text):
                    identity_names.extend([text.strip(), re.sub(r"[®–-]", " ", text).strip()])
        if method in {"semantic", "hybrid"}:
            ids = {row["chunk_id"] for row in ranked["results"]}
            cards = [card for card in cards if card.chunk_ids & ids]
        selected, gate = select_passages(cards, question, names + identity_names)
        traces.append({"plan_id": plan["plan_id"], "index_status": ranked.get("index_status"),
                       "timings": ranked["timings"], "source_gate": gate,
                       "ranks": [{"chunk_id": row["chunk_id"], "rank": row["rank"], "score": row["score"]}
                                 for row in ranked["results"]]})
        if not selected:
            clarify = gate.get("reason") in {"conflicting_documents", "no_service_requested", "too_many_service_contexts"}
            message = ("Please specify the service or document; the available source passages need more context."
                       if clarify else "I can’t establish every requested detail from the available source passages.")
            return _response("clarification_needed" if clarify else "insufficient_evidence", message,
                             plans, "retrieved_source", started,
                             details={"retrieval_method": method, "chunk_strategy": strategy, "retrieval": traces}, admin=admin)
        chosen.extend(project_passage(card, question) for card in selected)
    citations = list({(c.filename, c.page, c.section): c.citation for c in chosen}.values())
    display_names = {plan["plan_name"]: _display(plan) for plan in plans}
    display_labels = {c.label: re.sub(r"\bPCP\b", "PCP (primary care physician)", c.label) for c in chosen}
    quotes = [f"{display_names.get(c.plan_name, c.plan_name)} — {display_labels[c.label]}: “{c.wording}”" +
              (f" Source qualification: “{c.context}”" if c.kind == "exclusion" else "") for c in chosen]
    answer = "Source wording: " + " ".join(quotes)
    if any("cost sharing is based on" in c.wording.lower() for c in chosen):
        label = next(c.label.lower().replace(" ", "-") for c in chosen
                     if "cost sharing is based on" in c.wording.lower())
        answer = f"No single {label} price is listed here; the source states its conditions. " + answer
    if any(re.search(r"\b2\s*x\b", c.wording) for c in chosen):
        answer += " The source's 2 x cost share means twice the stated cost share."
    result = _response("answered", answer, plans, "retrieved_source", started, citations,
                       details={"retrieval_method": method, "chunk_strategy": strategy, "retrieval": traces}, admin=admin)
    result["_gemini_facts"] = {
        "kind": "source_passages", "facts": [{"plan": c.plan_name, "wording": c.wording} for c in chosen],
        "required_quotes": [c.wording for c in chosen] + [c.context for c in chosen if c.kind == "exclusion"],
    }
    return result


def answer_question(connection, question: str, context_plan_ids: list[int] | None = None,
                    previous_question: str | None = None, admin: bool = False,
                    method_override: str | None = None, strategy_override: str | None = None) -> dict:
    started = time.perf_counter()
    question = re.sub(r"\bdeductable(s?)\b", r"deductible\1", question, flags=re.I)
    plans = _approved_plans(connection)
    if not plans:
        return _response("insufficient_evidence", "No ready plan documents are available yet.", [],
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
        return _response("clarification_needed", "Which plan do you mean? Available plans: " +
                         "; ".join(_display(plan) for plan in plans) + ".", [], "plan_resolution", started,
                         details={"available_plan_ids": [plan["plan_id"] for plan in plans]}, admin=admin)
    if len(selected) > 1 and not comparison:
        return _response("clarification_needed", "Please name one plan, or ask to compare these plans: " +
                         "; ".join(_display(plan) for plan in selected) + ".", [], "plan_resolution", started,
                         details={"candidate_plan_ids": [plan["plan_id"] for plan in selected]}, admin=admin)
    network_comparison = bool(re.search(r"in[- ]network.*(?:versus|vs\.?|and).*out[- ]of[- ]network", question, re.I))
    if comparison and len(selected) < 2 and not network_comparison:
        return _response("clarification_needed", "Name at least two plans to compare, or ask to compare across all ready plans.",
                         selected, "plan_resolution", started, admin=admin)
    if comparison and len({plan["coverage_type"] for plan in selected}) > 1:
        return _response("clarification_needed", "These plans have different coverage types (medical, dental, or vision). Name plans with the same coverage type to compare.",
                         selected, "plan_resolution", started, admin=admin)
    year_gap = _unsupported_year(question, selected)
    if year_gap:
        return _response("insufficient_evidence", year_gap, selected, "plan_year", started,
                         details={"evidence_gate": "plan_year_mismatch"}, admin=admin)
    category = _category(question)
    followup = bool(re.match(r"^(what about|how about|and\b|for\b)", question.strip(), re.I))
    if not category and previous_question and len(question.split()) <= 8 and (followup or COMPARISON.search(question)):
        category = _category(previous_question)
    # Structured records remain authoritative for a single numerical dimension
    # and ordered comparisons. Service descriptions and compound requests use
    # complete source passages with their column context and qualifications.
    multi_context = (len([name for name, pattern in CATEGORIES if pattern.search(question)]) > 1
                     or bool(re.search(r"individual.*family|self.only.*family|in.network.*out.of.network", question, re.I)))
    numeric_lookup = bool(category and not multi_context and not _bare_deductible_request(question) and (
        (category == "deductible" and not re.search(r"happens|waiv|meet|combine|carryover", question, re.I)) or
        (category == "copay" and _qualifiers(question)) or
        re.search(r"\b(lower|higher|less|more)\b", question, re.I)))
    if numeric_lookup:
        composite = _multi_numeric_answer(connection, question, selected, started, admin)
        if composite is not None:
            return composite
        return _numeric_answer(connection, question, selected, category, started, admin)
    return _coverage_answer(connection, question, selected, plans, started, admin,
                            method_override, strategy_override)
