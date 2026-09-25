from datetime import datetime, timezone

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


def test_unresolved_candidate_and_unconfirmed_section_block_numeric_answer(monkeypatch):
    monkeypatch.setattr(answering, "_approved_plans", lambda _connection: MEDICAL[:1])
    monkeypatch.setattr(answering, "_benefits", lambda *_args: [
        benefit(1, "$500"), benefit(1, "$750", "pending_review")])
    result = answering.answer_question(None, "What is the Alpha Basic deductible?")
    assert result["status"] == "insufficient_evidence"
    assert "unresolved" in result["answer"]

    monkeypatch.setattr(answering, "_benefits", lambda *_args: [benefit(1, "$500", section_verified=False)])
    result = answering.answer_question(None, "What is the Alpha Basic deductible?")
    assert result["status"] == "insufficient_evidence"


def test_lower_followup_uses_context_and_identifies_plan(monkeypatch):
    monkeypatch.setattr(answering, "_approved_plans", lambda _connection: MEDICAL)
    monkeypatch.setattr(answering, "_benefits", lambda *_args: [benefit(1, "$500"), benefit(2, "$750")])
    result = answering.answer_question(None, "Which is lower?", [1, 2], "Compare deductibles")
    assert result["status"] == "answered"
    assert "Basic has the lowest" in result["answer"]
    assert len(result["citations"]) == 2


def test_table_citation_prefers_column_context_over_page_title():
    chunk = {"plan_name": "Basic", "original_filename": "plan.pdf", "chunk_id": 1,
             "rank": 1, "score": 1.0, "provenance": {"units": [{
                 "kind": "table_row", "page": 2, "section": "PLAN TITLE",
                 "headers": ["Benefits", "In Network"], "cells": ["Urgent care", "$20 copay"],
             }]}}
    result = answering._source_unit(chunk, {"urgent", "care"})
    assert result[1]["section"] == "Benefits | In Network"
