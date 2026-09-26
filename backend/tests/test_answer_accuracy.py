"""Answer-content regressions, separate from document/page retrieval hit rates.

Expected facts are authored independently of returned answers. Known product gaps
remain strict expected failures so they cannot be counted as correct answers.
"""

import json
from pathlib import Path
import re

import pytest

from app import answering, gemini


RETRIEVAL_CONFIGURATIONS = [
    ("bm25", "fixed_size"),
    ("bm25", "section_aware"),
    ("semantic", "fixed_size"),
    ("semantic", "section_aware"),
]


@pytest.fixture
def controlled_coverage_retrieval(monkeypatch):
    """Exercise answer checks independently of model/index availability."""
    plan = {"plan_id": 1, "insurer": "Alpha", "plan_name": "Basic",
            "plan_type": "hmo", "coverage_type": "medical"}
    chunk = {
        "chunk_id": 41, "document_id": 7, "plan_id": 1, "plan_name": "Basic",
        "original_filename": "Basic.pdf", "page_start": 3, "page_end": 3,
        "provenance": {"units": [{"kind": "text", "text": "Acupuncture services are covered.",
                                  "section": "Other covered services", "page": 3}]},
        "rank": 1, "score": 1.0,
    }
    monkeypatch.setattr(answering, "_approved_plans", lambda _connection: [plan])
    calls = []

    def retrieve(_connection, _query, method, strategy, **_kwargs):
        calls.append((method, strategy))
        return {"results": [chunk], "timings": {}}

    monkeypatch.setattr(answering, "retrieve", retrieve)
    return calls


@pytest.mark.parametrize("method,strategy", RETRIEVAL_CONFIGURATIONS)
def test_answer_accuracy_for_each_retrieval_configuration(
        controlled_coverage_retrieval, method, strategy):
    result = answering.answer_question(
        None, "Does Alpha Basic include acupuncture coverage?",
        method_override=method, strategy_override=strategy)

    assert result["status"] == "answered"
    assert "Acupuncture services are covered." in result["answer"]
    assert controlled_coverage_retrieval == [(method, strategy)]


@pytest.mark.parametrize("method,strategy", RETRIEVAL_CONFIGURATIONS)
def test_citation_accuracy_for_each_retrieval_configuration(
        controlled_coverage_retrieval, method, strategy):
    result = answering.answer_question(
        None, "Does Alpha Basic include acupuncture coverage?",
        method_override=method, strategy_override=strategy)

    assert result["citations"] == [{
        "plan": "Basic", "document": "Basic.pdf", "page": 3,
        "section": "Other covered services",
    }]


@pytest.mark.parametrize("method,strategy", RETRIEVAL_CONFIGURATIONS)
def test_abstention_accuracy_for_each_retrieval_configuration(
        controlled_coverage_retrieval, monkeypatch, method, strategy):
    monkeypatch.setattr(answering, "retrieve", lambda *_args, **_kwargs: {
        "results": [], "timings": {},
    })
    result = answering.answer_question(
        None, "Does Alpha Basic include acupuncture coverage?",
        method_override=method, strategy_override=strategy)

    assert result["status"] == "insufficient_evidence"
    assert result["citations"] == []
    assert "acupuncture" not in result["answer"].lower()


@pytest.mark.parametrize("question,wording,amounts,section", [
    ("What is the Kaiser Traditional individual deductible?",
     "Plan Deductible: None Individual", set(), "Out-of-Pocket Maximum(s) and Deductible(s)"),
    ("What is the Kaiser Traditional individual drug deductible?",
     "Drug Deductible: None Individual", set(), "Out-of-Pocket Maximum(s) and Deductible(s)"),
    ("What is the Kaiser Traditional emergency department cost?",
     "$50 per visit", {"$50"}, "Emergency Health Coverage You Pay"),
    ("Is urgent care covered under Kaiser Traditional?",
     "$30 per visit", {"$30"}, "Professional Services (Plan Provider office visits) You Pay"),
])
def test_pdf_answer_reports_expected_fact_and_exact_source(
        kaiser_connection, monkeypatch, question, wording, amounts, section):
    monkeypatch.setenv("GEMINI_ENABLED", "false")
    result = gemini.phrase_answer(answering.answer_question(
        kaiser_connection, question, method_override="bm25", strategy_override="section_aware"))

    assert result["status"] == "answered", result["answer"]
    assert wording in result["answer"]
    assert set(re.findall(r"\$[\d,]+(?:\.\d+)?|\d+%", result["answer"])) == amounts
    assert result["citations"] == [{
        "plan": "Traditional Plan", "document": "Kaiser HMO Plan Summary 2017.pdf",
        "page": 1, "section": section,
    }]


@pytest.mark.parametrize("question", [
    "What is the Kaiser Traditional out-of-network individual deductible?",
    "Is teleportation covered under Kaiser Traditional?",
])
def test_pdf_missing_evidence_does_not_report_a_benefit(kaiser_connection, question):
    result = answering.answer_question(
        kaiser_connection, question, method_override="bm25", strategy_override="section_aware")
    assert result["status"] == "insufficient_evidence"
    assert result["citations"] == []
    assert not re.search(r"\$|\d+%|\bno charge\b|\bno deductible\b", result["answer"], re.I)


def test_hospitalization_xray_matches_section_and_x_ray_wording(kaiser_connection):
    result = answering.answer_question(
        kaiser_connection, "How much is a hospitalization xray?",
        method_override="bm25", strategy_override="section_aware")
    assert result["status"] == "answered", result["answer"]
    assert "X-rays" in result["answer"]
    assert "$500 per admission" in result["answer"]
    assert result["citations"] == [{
        "plan": "Traditional Plan", "document": "Kaiser HMO Plan Summary 2017.pdf",
        "page": 1, "section": "Hospitalization Services You Pay",
    }]


def test_specific_long_mail_order_question_uses_cited_source_row(kaiser_connection):
    result = answering.answer_question(
        kaiser_connection, "What about Most generic refills through our mail-order service?",
        method_override="bm25", strategy_override="section_aware")
    assert result["status"] == "answered", result["answer"]
    assert "Most generic refills through our mail-order service" in result["answer"]
    assert "$20 for up to a 100-day supply" in result["answer"]
    assert result["citations"] == [{
        "plan": "Traditional Plan", "document": "Kaiser HMO Plan Summary 2017.pdf",
        "page": 1, "section": "Prescription Drug Coverage You Pay",
    }]


def test_brand_name_mail_order_followup_uses_current_source_row(kaiser_connection):
    result = answering.answer_question(
        kaiser_connection, "Most brand-name refills through our mail-order service ?",
        context_plan_ids=[1],
        previous_question="What about Most generic refills through our mail-order service?",
        method_override="bm25", strategy_override="section_aware")
    assert result["status"] == "answered", result["answer"]
    assert "Most brand-name refills through our mail-order service" in result["answer"]
    assert "$40 for up to a 100-day supply" in result["answer"]
    assert "$20" not in result["answer"]
    assert result["citations"] == [{
        "plan": "Traditional Plan", "document": "Kaiser HMO Plan Summary 2017.pdf",
        "page": 1, "section": "Prescription Drug Coverage You Pay",
    }]


@pytest.fixture
def controlled_benefits(monkeypatch):
    """Synthetic competing values expose wrong-plan/network/scope selection."""
    plans = [
        {"plan_id": 1, "insurer": "Alpha", "plan_name": "Basic", "plan_type": "hmo", "coverage_type": "medical"},
        {"plan_id": 2, "insurer": "Beta", "plan_name": "Plus", "plan_type": "ppo", "coverage_type": "medical"},
    ]
    rows = []
    for plan_id, name, network, scope, amount in [
        (1, "Basic", "in-network", "individual", "$500"),
        (1, "Basic", "in-network", "family", "$1,000"),
        (1, "Basic", "out-of-network", "individual", "$1,500"),
        (1, "Basic", "out-of-network", "family", "$3,000"),
        (2, "Plus", "in-network", "individual", "$750"),
    ]:
        rows.append({
            "benefit_id": len(rows) + 1, "plan_id": plan_id, "category": "deductible",
            "value_text": f"{network} {scope} deductible: {amount}",
            "dimensions": {"network": network, scope: scope},
            "verification_status": "pending_review", "reviewed_at": None,
            "source_section_verified": False, "section": "Annual deductible",
            "page_number": 2, "parse_status": "parsed", "document_id": plan_id,
            "original_filename": f"{name}.pdf", "plan_name": name,
        })
    monkeypatch.setattr(answering, "_approved_plans", lambda _: plans)
    monkeypatch.setattr(answering, "_benefits", lambda _connection, ids, category: [
        row for row in rows if row["plan_id"] in ids and row["category"] == category])
    return rows


@pytest.mark.parametrize("network,scope,expected", [
    ("in-network", "individual", "$500"),
    ("in-network", "family", "$1,000"),
    ("out-of-network", "individual", "$1,500"),
    ("out-of-network", "family", "$3,000"),
])
def test_answer_selects_correct_network_and_family_amount(controlled_benefits, network, scope, expected):
    result = answering.answer_question(None, f"What is the Alpha Basic {network} {scope} deductible?")
    assert result["status"] == "answered"
    assert f"Basic: {network} {scope} deductible: {expected}" in result["answer"]
    assert re.findall(r"\$[\d,]+", result["answer"]) == [expected]
    assert result["citations"] == [{"plan": "Basic", "section": "Annual deductible",
                                    "page": 2, "document": "Basic.pdf"}]


@pytest.mark.parametrize("direction,winner", [("lower", "Basic"), ("higher", "Plus")])
def test_comparison_reports_correct_winner_and_plan_value_pairs(controlled_benefits, direction, winner):
    result = answering.answer_question(None, f"Which in-network individual deductible is {direction} across plans?")
    assert result["status"] == "answered"
    assert f"{winner} has the {'lowest' if direction == 'lower' else 'highest'} deductible" in result["answer"]
    assert "Basic: in-network individual deductible: $500" in result["answer"]
    assert "Plus: in-network individual deductible: $750" in result["answer"]
    assert set(re.findall(r"\$[\d,]+", result["answer"])) == {"$500", "$750"}
    assert [(c["plan"], c["document"], c["page"]) for c in result["citations"]] == [
        ("Basic", "Basic.pdf", 2), ("Plus", "Plus.pdf", 2)]


def test_unspecified_context_requests_clarification_without_selecting_amount(controlled_benefits):
    result = answering.answer_question(None, "What is the Alpha Basic deductible?")
    assert result["status"] == "clarification_needed"
    assert result["citations"] == []
    assert "$" not in result["answer"]


@pytest.mark.parametrize("missing_field", ["section", "page_number"])
def test_correct_amount_without_source_provenance_is_not_reported(controlled_benefits, missing_field):
    controlled_benefits[0][missing_field] = None
    result = answering.answer_question(None, "What is the Alpha Basic in-network individual deductible?")
    assert result["status"] == "insufficient_evidence"
    assert result["citations"] == []
    assert "$" not in result["answer"]


@pytest.mark.parametrize("service", ["primary care", "specialist"])
def test_pdf_office_visit_answer_accuracy(kaiser_connection, service):
    result = answering.answer_question(kaiser_connection,
                                       f"What is the Kaiser Traditional {service} copay?")
    assert result["status"] == "answered", result["answer"]
    assert "$30 per visit" in result["answer"]
    assert result["citations"][0]["page"] == 1


def test_manifest_emergency_answer_includes_admission_exception(kaiser_connection):
    manifest = json.loads((Path(__file__).resolve().parents[2] / "evaluation/questions.json").read_text())
    question = next(q for q in manifest["questions"] if q["question_id"] == "kaiser_traditional_03")
    result = answering.answer_question(kaiser_connection, question["question"])
    assert result["status"] == "answered", result["answer"]
    assert "$50 per visit" in result["answer"]
    assert "does not apply" in result["answer"].lower()
    assert "admitted" in result["answer"].lower()
    assert result["citations"][0]["page"] == 1
