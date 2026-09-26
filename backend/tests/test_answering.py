from datetime import datetime, timezone

import pytest

from app import answering
from app.retrieval import retrieve


MEDICAL = [
    {"plan_id": 1, "insurer": "Alpha", "plan_name": "Basic", "plan_type": "hmo", "coverage_type": "medical"},
    {"plan_id": 2, "insurer": "Beta", "plan_name": "Plus", "plan_type": "ppo", "coverage_type": "medical"},
]


def benefit(plan_id, value, status="verified", section_verified=True):
    return {
        "benefit_id": plan_id, "plan_id": plan_id, "category": "deductible",
        "value_text": f"Deductible: {value}", "dimensions": {"network": "in-network"},
        "verification_status": status, "reviewed_at": datetime.now(timezone.utc),
        "source_section_verified": section_verified, "section": "Plan costs",
        "page_number": 2, "parse_status": "parsed", "document_id": plan_id,
        "original_filename": f"plan-{plan_id}.pdf", "plan_name": MEDICAL[plan_id - 1]["plan_name"],
    }


def test_short_insurer_names_resolve_plans():
    plans = [
        {"plan_id": 1, "insurer": "Aetna Health of California Inc.", "plan_name": "HMO - California", "plan_type": "hmo", "coverage_type": "medical"},
        {"plan_id": 2, "insurer": "Aetna Life Insurance Company", "plan_name": "Open Access Managed Choice POS", "plan_type": "pos", "coverage_type": "medical"},
        {"plan_id": 3, "insurer": "Kaiser Permanente", "plan_name": "Traditional Plan", "plan_type": "hmo", "coverage_type": "medical"},
        {"plan_id": 4, "insurer": "Group Health Cooperative", "plan_name": "Multisite", "plan_type": "unknown", "coverage_type": "medical"},
    ]
    ids = lambda question: [plan["plan_id"] for plan in answering._matches(question, plans)]
    assert ids("What is the Kaiser deductible?") == [3]
    assert ids("What is the Aetna HMO deductible?") == [1]
    assert ids("Aetna deductible") == [1, 2]
    assert ids("Group Health deductible") == [4]
    assert ids("What is the deductible?") == []


def test_guardian_product_names_resolve_their_own_plan():
    plans = [
        {"plan_id": 1, "insurer": "Guardian", "plan_name": "Guardian DentalGuard Preferred PPO",
         "plan_type": "ppo", "coverage_type": "dental"},
        {"plan_id": 2, "insurer": "Guardian", "plan_name": "Guardian VSP Vision",
         "plan_type": "unknown", "coverage_type": "vision"},
    ]
    assert [plan["plan_id"] for plan in answering._matches("Guardian DentalGuard Preferred", plans)] == [1]
    assert [plan["plan_id"] for plan in answering._matches("Guardian VSP frames", plans)] == [2]


def test_compound_source_rows_from_conflicting_documents_require_review(monkeypatch):
    plan = MEDICAL[0]
    chunks = [{"chunk_id": index, "document_id": index, "plan_id": 1,
               "plan_name": "Basic", "original_filename": f"plan-{index}.pdf",
               "provenance": {"units": [{"kind": "table_row", "page": 1,
                                         "section": "EMERGENCY CARE", "headers": ["Service", "You Pay"],
                                         "cells": ["Emergency Room", f"${amount} copay"]}]}}
              for index, amount in ((1, 100), (2, 200))]
    monkeypatch.setattr(answering, "_approved_plans", lambda _connection: [plan])
    monkeypatch.setattr(answering, "approved_chunks", lambda *_args, **_kwargs: chunks)
    monkeypatch.setattr(answering, "retrieve", lambda *_args, **_kwargs: {
        "results": [{**chunk, "rank": index, "score": 1.0} for index, chunk in enumerate(chunks, 1)],
        "timings": {},
    })
    result = answering.answer_question(None, "What is the emergency room cost?")
    assert result["status"] == "clarification_needed"
    assert result["citations"] == []


def test_mixed_coverage_comparison_requires_clarification(monkeypatch):
    plans = [MEDICAL[0], {**MEDICAL[1], "coverage_type": "dental"}]
    monkeypatch.setattr(answering, "_approved_plans", lambda _connection: plans)
    result = answering.answer_question(None, "Compare deductibles across plans")
    assert result["status"] == "clarification_needed"
    assert "different coverage types" in result["answer"]


def test_explicit_coverage_type_limits_across_plan_comparison(monkeypatch):
    plans = MEDICAL + [{"plan_id": 3, "insurer": "Gamma", "plan_name": "Dental", "plan_type": "ppo", "coverage_type": "dental"}]
    monkeypatch.setattr(answering, "_approved_plans", lambda _connection: plans)
    monkeypatch.setattr(answering, "_benefits", lambda *_args: [benefit(1, "$500"), benefit(2, "$750")])
    result = answering.answer_question(None, "Compare medical deductibles across all plans")
    assert result["status"] == "answered"
    assert result["context_plan_ids"] == [1, 2]


def test_conflicting_candidate_and_unconfirmed_reviewed_section_block_numeric_answer(monkeypatch):
    monkeypatch.setattr(answering, "_approved_plans", lambda _connection: MEDICAL[:1])
    monkeypatch.setattr(answering, "_benefits", lambda *_args: [
        benefit(1, "$500"), benefit(1, "$750", "pending_review")])
    result = answering.answer_question(None, "What is the Alpha Basic deductible?")
    assert result["status"] == "insufficient_evidence"
    assert "conflicting" in result["answer"]

    monkeypatch.setattr(answering, "_benefits", lambda *_args: [benefit(1, "$500", section_verified=False)])
    result = answering.answer_question(None, "What is the Alpha Basic deductible?")
    assert result["status"] == "insufficient_evidence"


def test_unresolved_candidate_with_unknown_context_blocks_qualified_answer(monkeypatch):
    monkeypatch.setattr(answering, "_approved_plans", lambda _connection: MEDICAL[:1])
    unresolved = benefit(1, "$750", "pending_review")
    unresolved["dimensions"] = {}
    monkeypatch.setattr(answering, "_benefits", lambda *_args: [benefit(1, "$500"), unresolved])

    result = answering.answer_question(None, "What is the Alpha Basic in-network deductible?")

    assert result["status"] == "insufficient_evidence"
    assert "conflicting" in result["answer"]


def test_unambiguous_automatic_candidate_answers_with_citation(monkeypatch):
    monkeypatch.setattr(answering, "_approved_plans", lambda _connection: MEDICAL[:1])
    row = benefit(1, "$500", "pending_review", section_verified=False)
    row["reviewed_at"] = None
    monkeypatch.setattr(answering, "_benefits", lambda *_args: [row])

    result = answering.answer_question(None, "What is the Alpha Basic in-network deductible?")

    assert result["status"] == "answered"
    assert result["citations"][0]["page"] == 2
    assert result["citations"][0]["section"] == "Plan costs"


def test_ambiguous_candidate_blocks_only_matching_context(monkeypatch):
    monkeypatch.setattr(answering, "_approved_plans", lambda _connection: MEDICAL[:1])
    supported = benefit(1, "$500", "pending_review")
    ambiguous = benefit(1, "$700 or $900", "ambiguous")
    ambiguous["dimensions"] = {"network": "out-of-network"}
    monkeypatch.setattr(answering, "_benefits", lambda *_args: [supported, ambiguous])

    assert answering.answer_question(None, "What is the Alpha Basic in-network deductible?")["status"] == "answered"
    assert answering.answer_question(None, "What is the Alpha Basic out-of-network deductible?")["status"] == "insufficient_evidence"


def test_unresolved_candidate_in_a_known_different_context_does_not_block(monkeypatch):
    monkeypatch.setattr(answering, "_approved_plans", lambda _connection: MEDICAL[:1])
    unresolved = benefit(1, "$750", "pending_review")
    unresolved["dimensions"] = {"network": "out-of-network"}
    monkeypatch.setattr(answering, "_benefits", lambda *_args: [benefit(1, "$500"), unresolved])

    result = answering.answer_question(None, "What is the Alpha Basic in-network deductible?")

    assert result["status"] == "answered"


def test_lower_followup_uses_context_and_identifies_plan(monkeypatch):
    monkeypatch.setattr(answering, "_approved_plans", lambda _connection: MEDICAL)
    monkeypatch.setattr(answering, "_benefits", lambda *_args: [benefit(1, "$500"), benefit(2, "$750")])
    result = answering.answer_question(None, "Which is lower?", [1, 2], "Compare deductibles")
    assert result["status"] == "answered"
    assert "Basic has the lowest" in result["answer"]
    assert len(result["citations"]) == 2


def test_copay_lookup_filters_network_scope_and_service(monkeypatch):
    monkeypatch.setattr(answering, "_approved_plans", lambda _connection: MEDICAL[:1])
    candidates = [
        {**benefit(1, "$25"), "category": "copay", "value_text": "Urgent care copay: $25",
         "dimensions": {"network": "in-network", "family": "Family", "service": "urgent care"}},
        {**benefit(1, "$15"), "category": "copay", "value_text": "Primary care copay: $15",
         "dimensions": {"network": "in-network", "family": "Family", "service": "primary care"}},
        {**benefit(1, "$40"), "category": "copay", "value_text": "Urgent care copay: $40",
         "dimensions": {"network": "out-of-network", "family": "Family", "service": "urgent care"}},
        {**benefit(1, "$20"), "category": "copay", "value_text": "Urgent care copay: $20",
         "dimensions": {"network": "in-network", "individual": "Individual", "service": "urgent care"}},
        {**benefit(1, "$50", "pending_review"), "category": "copay",
         "value_text": "Urgent care copay: $50",
         "dimensions": {"network": "out-of-network", "family": "Family", "service": "urgent care"}},
    ]
    monkeypatch.setattr(answering, "_benefits", lambda *_args: candidates)

    result = answering.answer_question(
        None, "What is the Alpha Basic in-network family urgent care copay?"
    )

    assert result["status"] == "answered"
    assert "Urgent care copay: $25" in result["answer"]
    assert "$15" not in result["answer"]
    assert "$40" not in result["answer"]
    assert "$20" not in result["answer"]


@pytest.mark.parametrize(("basic_value", "plus_value"), [("$500", "20%"), ("$500", "not covered")])
def test_lower_comparison_clarifies_for_incomparable_or_nonnumeric_values(
        monkeypatch, basic_value, plus_value):
    monkeypatch.setattr(answering, "_approved_plans", lambda _connection: MEDICAL)
    monkeypatch.setattr(answering, "_benefits", lambda *_args: [
        benefit(1, basic_value), benefit(2, plus_value)
    ])

    result = answering.answer_question(None, "Which deductible is lower across plans?")

    assert result["status"] == "clarification_needed"
    assert "different or nonnumeric units" in result["answer"]


def test_comparison_clarifies_when_benefit_dimensions_differ(monkeypatch):
    monkeypatch.setattr(answering, "_approved_plans", lambda _connection: MEDICAL)
    in_network = benefit(1, "$500")
    out_of_network = benefit(2, "$750")
    out_of_network["dimensions"] = {"network": "out-of-network"}
    monkeypatch.setattr(answering, "_benefits", lambda *_args: [in_network, out_of_network])

    result = answering.answer_question(None, "Which deductible is lower across plans?")

    assert result["status"] == "clarification_needed"
    assert "different network" in result["answer"]


def test_table_citation_uses_service_label_when_page_section_is_title():
    chunk = {"plan_name": "Basic", "original_filename": "plan.pdf", "chunk_id": 1,
             "rank": 1, "score": 1.0, "provenance": {"units": [{
                 "kind": "table_row", "page": 2, "section": "PLAN TITLE",
                 "headers": ["Benefits", "In Network"], "cells": ["Urgent care", "$20 copay"],
             }]}}
    result = answering._source_unit(chunk, {"urgent", "care"})
    assert result[1]["section"] == "Urgent care"


def test_text_citation_rejects_plan_title_as_section():
    for title in ("ALPHA BASIC 2025 PLAN", "SUMMARY OF BENEFITS AND COVERAGE"):
        chunk = {"plan_name": "Basic", "original_filename": "plan.pdf", "chunk_id": 1,
                 "rank": 1, "score": 1.0, "provenance": {"units": [{
                     "kind": "text", "page": 1, "section": title,
                     "line": 1, "text": "Urgent care visits are covered with a $20 copay.",
                 }]}}

        assert answering._source_unit(chunk, {"urgent", "care"}) is None


def test_text_citation_keeps_relevant_benefit_section():
    chunk = {"plan_name": "Basic", "original_filename": "plan.pdf", "chunk_id": 1,
             "rank": 1, "score": 1.0, "provenance": {"units": [{
                 "kind": "text", "page": 2, "section": "URGENT CARE",
                 "line": 1, "text": "Urgent care visits are covered with a $20 copay.",
             }]}}

    result = answering._source_unit(chunk, {"urgent", "care"})

    assert result[1]["section"] == "URGENT CARE"


def test_kaiser_pdf_flows_through_bm25_and_cited_answers(kaiser_connection):
    connection = kaiser_connection
    search = retrieve(connection, "urgent care", "bm25", "section_aware", top_k=10)
    assert search["results"]
    assert any("Urgent care consultations" in row["chunk_text"] for row in search["results"])

    coverage = answering.answer_question(
        connection, "Is urgent care covered under the Kaiser Permanente Traditional Plan?")
    assert coverage["status"] == "answered"
    assert "Urgent care consultations" in coverage["answer"]
    assert coverage["citations"][0]["section"] == "Professional Services (Plan Provider office visits) You Pay"

    deductible = answering.answer_question(
        connection, "What is the Kaiser Permanente Traditional Plan individual deductible?")
    assert deductible["status"] == "answered"
    assert "Plan Deductible: None Individual" in deductible["answer"]
    assert "$0" not in deductible["answer"]
    assert deductible["citations"][0]["section"] == "Out-of-Pocket Maximum(s) and Deductible(s)"

    drug_deductible = answering.answer_question(
        connection, "What is the Kaiser Permanente Traditional Plan individual drug deductible?")
    assert drug_deductible["status"] == "answered"
    assert "Drug Deductible: None Individual" in drug_deductible["answer"]

    emergency = answering.answer_question(
        connection, "What is the Kaiser Permanente Traditional Plan emergency department cost?")
    assert emergency["status"] == "answered"
    assert "$50 per visit" in emergency["answer"]
    assert emergency["citations"][0]["section"] == "Emergency Health Coverage You Pay"

    unsupported = answering.answer_question(
        connection, "What is the Kaiser Permanente Traditional Plan out-of-network individual deductible?")
    assert unsupported["status"] == "insufficient_evidence"
    assert unsupported["citations"] == []


def test_none_only_counts_when_stated_as_a_deductible_value():
    assert answering._value({"category": "deductible", "value_text": "Plan Deductible: None Individual"}) == "none"
    assert answering._value({"category": "deductible", "value_text": "None of these; deductible: $500"}) == "$500"
    assert answering._value({"category": "copay", "value_text": "None of these copays apply"}) is None
    assert answering._ordered_value("none") is None


@pytest.mark.parametrize("plan_year, status", [(2017, "insufficient_evidence"), (None, "insufficient_evidence"),
                                               (2019, "answered")])
def test_question_year_must_match_the_plan_year(monkeypatch, plan_year, status):
    plan = {**MEDICAL[0], "plan_year": plan_year}
    monkeypatch.setattr(answering, "_approved_plans", lambda _connection: [plan])
    monkeypatch.setattr(answering, "_benefits", lambda *_args: [benefit(1, "$500")])
    result = answering.answer_question(None, "What is the Basic deductible for 2019?")
    assert result["status"] == status
    if status != "answered":
        assert "2019" in result["answer"] and result["citations"] == []


def test_dollar_amounts_are_not_mistaken_for_years(monkeypatch):
    plan = {**MEDICAL[0], "plan_year": 2017}
    monkeypatch.setattr(answering, "_approved_plans", lambda _connection: [plan])
    monkeypatch.setattr(answering, "_benefits", lambda *_args: [benefit(1, "$2000")])
    assert answering.answer_question(None, "Is the Basic deductible $2000?")["status"] == "answered"
