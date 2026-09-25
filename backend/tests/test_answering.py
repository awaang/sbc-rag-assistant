from datetime import datetime, timezone

import pytest

from app import answering


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


def test_table_citation_prefers_column_context_over_page_title():
    chunk = {"plan_name": "Basic", "original_filename": "plan.pdf", "chunk_id": 1,
             "rank": 1, "score": 1.0, "provenance": {"units": [{
                 "kind": "table_row", "page": 2, "section": "PLAN TITLE",
                 "headers": ["Benefits", "In Network"], "cells": ["Urgent care", "$20 copay"],
             }]}}
    result = answering._source_unit(chunk, {"urgent", "care"})
    assert result[1]["section"] == "Benefits | In Network"


def test_text_citation_rejects_plan_title_as_section():
    for title in ("ALPHA BASIC 2025 PLAN", "SUMMARY OF BENEFITS AND COVERAGE"):
        chunk = {"plan_name": "Basic", "original_filename": "plan.pdf", "chunk_id": 1,
                 "rank": 1, "score": 1.0, "provenance": {"units": [{
                     "kind": "text", "page": 1, "section": title,
                     "line": "Urgent care visits are covered with a $20 copay.",
                 }]}}

        assert answering._source_unit(chunk, {"urgent", "care"}) is None


def test_text_citation_keeps_relevant_benefit_section():
    chunk = {"plan_name": "Basic", "original_filename": "plan.pdf", "chunk_id": 1,
             "rank": 1, "score": 1.0, "provenance": {"units": [{
                 "kind": "text", "page": 2, "section": "URGENT CARE",
                 "line": "Urgent care visits are covered with a $20 copay.",
             }]}}

    result = answering._source_unit(chunk, {"urgent", "care"})

    assert result[1]["section"] == "URGENT CARE"
