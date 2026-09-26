"""Corpus-based checks for all 30 labeled PDF questions.

Answerable questions get answer, citation, and missing-evidence checks; abstention and
clarification questions get a no-value, no-citation check. Questions with a manifest
``known_gap`` are reported as strict expected failures. These exercise PDF parsing,
benefit extraction, section-aware chunks, real BM25 retrieval, and the deterministic
answer gate. Gemini phrasing is evaluated separately.
"""

import hashlib
import json
import re
from decimal import Decimal
from pathlib import Path

import pytest

from app.answering import answer_question
from app.benefits import extract_candidates
from app.ingestion import build_chunks, parse_pdf
from app.source_catalog import build_catalog, select_passages, terms


ROOT = Path(__file__).resolve().parents[2]
MANIFEST = json.loads((ROOT / "evaluation/questions.json").read_text())
METADATA = json.loads((ROOT / "data/source-documents/received/metadata.json").read_text())
QUESTIONS = MANIFEST["questions"]
assert len(QUESTIONS) == 30
assert len({item["question_id"] for item in QUESTIONS}) == len(QUESTIONS)
AMOUNT = re.compile(r"\$\s?\d[\d,]*(?:\.\d+)?|\b\d+(?:\.\d+)?\s?%")
STATUSES = {"answered", "insufficient_evidence", "clarification_needed"}
assert all(item["expected_status"] in STATUSES for item in QUESTIONS)
assert all(item.get("required_phrases") for item in QUESTIONS if item["expected_status"] == "answered")


def with_known_gap(items):
    return [pytest.param(item, id=item["question_id"], marks=pytest.mark.xfail(
                strict=True, reason=item["known_gap"])) if item.get("known_gap")
            else pytest.param(item, id=item["question_id"]) for item in items]


ANSWERABLE = [item for item in QUESTIONS if item["expected_status"] == "answered"]
NOT_ANSWERABLE = [item for item in QUESTIONS if item["expected_status"] != "answered"]


def amount_key(value):
    compact = value.replace(" ", "").replace(",", "")
    return (compact[0], Decimal(compact[1:-1] if compact.endswith("%") else compact[1:]))


class Rows:
    def __init__(self, rows):
        self.rows = rows

    def fetchall(self):
        return self.rows


class PDFCorpus:
    def __init__(self, plans, chunks, benefits, excluded_document_ids=frozenset()):
        self.plans = plans
        self.chunks = chunks
        self.benefits = benefits
        self.excluded_document_ids = excluded_document_ids

    def without_evidence(self, document_ids):
        return PDFCorpus(self.plans, self.chunks, self.benefits, frozenset(document_ids))

    def execute(self, sql, params=()):
        if "FROM plans p JOIN documents" in sql:
            return Rows(self.plans)
        if "FROM benefit_records b" in sql:
            plan_ids, category = params[:2]
            return Rows([row for row in self.benefits
                         if row["plan_id"] in plan_ids and row["category"] == category
                         and row["document_id"] not in self.excluded_document_ids])
        if "FROM chunks c JOIN documents d" in sql:
            strategy = params[0]
            plan_id = params[2] if len(params) > 2 else None
            return Rows([row for row in self.chunks if row["chunk_strategy"] == strategy
                         and (plan_id is None or row["plan_id"] == plan_id)
                         and row["document_id"] not in self.excluded_document_ids])
        raise AssertionError(sql)


@pytest.fixture(scope="module")
def pdf_corpus():
    plans, chunks, benefits = [], [], []
    ids_by_source = {}
    filenames_by_source = {}
    for document_id, document in enumerate(METADATA["documents"], 1):
        path = ROOT / "data/source-documents/received" / document["original_filename"]
        data = path.read_bytes()
        assert hashlib.sha256(data).hexdigest() == document["sha256"]
        pages = parse_pdf(data)
        plan = {"plan_id": document_id, "insurer": document["insurer"],
                "plan_name": document["plan_name"],
                "plan_type": (document["plan_type"] or "unknown").lower(),
                "coverage_type": document["coverage_type"]}
        plans.append(plan)
        ids_by_source[document["document_id"]] = document_id
        filenames_by_source[document["document_id"]] = path.name
        for strategy, items in build_chunks(pages).items():
            for item in items:
                chunks.append({"chunk_id": len(chunks) + 1, "document_id": document_id,
                               "plan_id": document_id, "plan_name": plan["plan_name"],
                               "original_filename": path.name, "chunk_strategy": strategy,
                               "chunk_text": item["text"], "page_start": item["page_start"],
                               "page_end": item["page_end"], "provenance": item["provenance"]})
        for candidate in extract_candidates(pages):
            benefits.append({"benefit_id": len(benefits) + 1, "plan_id": document_id,
                             "category": candidate.category, "value_text": candidate.value_text,
                             "dimensions": candidate.dimensions, "verification_status": candidate.status,
                             "reviewed_at": None, "source_section_verified": False,
                             "section": candidate.section, "page_number": candidate.page_number,
                             "parse_status": "parsed", "document_id": document_id,
                             "original_filename": path.name, "plan_name": plan["plan_name"]})
    return PDFCorpus(plans, chunks, benefits), ids_by_source, filenames_by_source


@pytest.fixture(scope="module")
def pdf_answers(pdf_corpus):
    corpus, ids_by_source, _ = pdf_corpus
    return {item["question_id"]: answer_question(
        corpus, item["question"],
        context_plan_ids=[ids_by_source[source] for source in item["source_document_ids"]] or None,
        method_override="bm25", strategy_override="section_aware")
        for item in QUESTIONS}


@pytest.mark.parametrize("question, wording, section, page", [
    ("What are the Group Health Cooperative Multisite outpatient office visits?",
     "$20", "Outpatient services (Office visits)", 1),
    ("What is the Group Health Cooperative Multisite prescription mail order cost share?",
     "2 x prescription cost share per 90 day supply", "Prescription mail order", 1),
])
def test_headingless_group_health_table_rows_are_citable(pdf_corpus, question, wording, section, page):
    corpus, ids_by_source, _ = pdf_corpus
    result = answer_question(
        corpus, question, context_plan_ids=[ids_by_source["candidate-group-health-cooperative-wa-2017"]],
        method_override="bm25", strategy_override="section_aware")
    assert result["status"] == "answered", result["answer"]
    assert wording in result["answer"]
    assert result["citations"] == [{
        "plan": "Multisite Benefit Summary", "document": "Kaiser WA.pdf",
        "page": page, "section": section,
    }]


def test_pos_infertility_cost_uses_qualified_source_without_inventing_price(pdf_corpus):
    corpus, ids_by_source, _ = pdf_corpus
    result = answer_question(
        corpus, "Infertility Treatment cost",
        context_plan_ids=[ids_by_source["candidate-aetna-oamc-2017"]],
        method_override="bm25", strategy_override="section_aware")
    assert result["status"] == "answered", result["answer"]
    assert "No single infertility-treatment price" in result["answer"]
    assert "type of service and where it is" in result["answer"]
    assert "underlying medical condition only" in result["answer"]
    assert "$" not in result["answer"]
    assert result["citations"] == [{
        "plan": "Aetna Open Access Managed Choice POS",
        "document": "Aetna OAMC Plan Summary  01.01.2017.pdf",
        "page": 4, "section": "FAMILY PLANNING",
    }]


def test_misspelled_bare_deductible_uses_both_source_rows_and_table_headers(pdf_corpus):
    corpus, ids_by_source, _ = pdf_corpus
    result = answer_question(
        corpus, "what is deductable",
        context_plan_ids=[ids_by_source["candidate-aetna-oamc-2017"]],
        method_override="bm25", strategy_override="section_aware")
    assert result["status"] == "answered", result["answer"]
    for value in ("$300 Individual", "$600 Individual", "$600 Family", "$1,200 Family"):
        assert value in result["answer"]
    assert "IN-NETWORK" in result["answer"]
    assert "OUT-OF-NETWORK" in result["answer"]
    assert result["citations"] == [{
        "plan": "Aetna Open Access Managed Choice POS",
        "document": "Aetna OAMC Plan Summary  01.01.2017.pdf",
        "page": 1, "section": "PLAN FEATURES",
    }]


def test_kaiser_inpatient_hospital_request_uses_hospitalization_row(pdf_corpus):
    corpus, ids_by_source, _ = pdf_corpus
    result = answer_question(
        corpus, "What does the Kaiser Traditional plan charge for inpatient hospital services?",
        context_plan_ids=[ids_by_source["candidate-kaiser-traditional-2017"]],
        method_override="bm25", strategy_override="section_aware")
    assert result["status"] == "answered", result["answer"]
    assert "Room and board, surgery, anesthesia, X-rays, laboratory tests, and drugs" in result["answer"]
    assert "$500 per admission" in result["answer"]
    assert result["citations"] == [{
        "plan": "Traditional Plan", "document": "Kaiser HMO Plan Summary 2017.pdf",
        "page": 1, "section": "Hospitalization Services You Pay",
    }]


def test_kaiser_inpatient_psychiatric_request_uses_its_specific_row(pdf_corpus):
    corpus, ids_by_source, _ = pdf_corpus
    result = answer_question(
        corpus, "What is the Kaiser Traditional inpatient psychiatric hospitalization cost?",
        context_plan_ids=[ids_by_source["candidate-kaiser-traditional-2017"]],
        method_override="bm25", strategy_override="section_aware")
    assert result["status"] == "answered", result["answer"]
    assert "Inpatient psychiatric hospitalization" in result["answer"]
    assert "Room and board" not in result["answer"]
    assert "$500 per admission" in result["answer"]


def test_multirow_answer_cites_both_office_visit_pages(pdf_answers):
    result = pdf_answers["aetna_hmo_03"]
    assert {(citation["page"], citation["section"]) for citation in result["citations"]} == {
        (1, "PHYSICIAN SERVICES"), (2, "Specialist Office Visits")}


def test_every_extracted_benefit_entry_is_reachable_with_its_plan_and_source_context(pdf_corpus):
    """Full-corpus selector audit across all benefit rows, beyond the 30 authored Q&A cases."""
    corpus, _, _ = pdf_corpus
    checked = 0
    for plan in corpus.plans:
        chunks = [chunk for chunk in corpus.chunks
                  if chunk["plan_id"] == plan["plan_id"] and chunk["chunk_strategy"] == "section_aware"]
        cards = build_catalog(chunks)
        names = [plan["plan_name"], plan["insurer"]]
        for card in cards:
            if card.kind != "benefit":
                continue
            # Long labels are tested directly; short tier labels need the source section.
            query_label = card.label
            if terms(card.label) <= {"inpatient", "outpatient", "retail", "mailorder", "generic", "preferred", "specialty"}:
                query_label = f"{card.section} {card.context} {card.label}"
            question = f"What does the plan say about {query_label}?"
            passages, gate = select_passages(cards, question, names)
            assert any((card.filename, card.page, card.section) ==
                       (item.filename, item.page, item.section) and card.label == item.label
                       for item in passages), (plan["plan_name"], card, gate)
            checked += 1
    assert checked == 283


def test_every_extracted_exclusion_entry_is_reachable_as_an_exclusion(pdf_corpus):
    """An exclusion query must not resolve to a same-named covered-benefit row."""
    corpus, _, _ = pdf_corpus
    checked = 0
    for plan in corpus.plans:
        chunks = [chunk for chunk in corpus.chunks
                  if chunk["plan_id"] == plan["plan_id"] and chunk["chunk_strategy"] == "section_aware"]
        cards = build_catalog(chunks)
        for card in cards:
            if card.kind != "exclusion":
                continue
            question = f"What exclusions apply to {card.label}?"
            passages, gate = select_passages(cards, question, [plan["plan_name"], plan["insurer"]])
            assert any(item.kind == "exclusion" and item.filename == card.filename
                       and item.page == card.page and item.label == card.label for item in passages), (
                           plan["plan_name"], card, gate)
            checked += 1
    assert checked == 43


@pytest.mark.parametrize("item", with_known_gap(ANSWERABLE))
def test_pdf_answer_accuracy(item, pdf_answers):
    result = pdf_answers[item["question_id"]]
    assert result["status"] == "answered", result["answer"]
    expected_amounts = {amount_key(amount) for amount in AMOUNT.findall(item["expected_answer"])}
    actual_amounts = {amount_key(amount) for amount in AMOUNT.findall(result["answer"])}
    assert expected_amounts <= actual_amounts, result["answer"]
    forbidden_amounts = {amount_key(amount) for amount in item.get("forbidden_amounts", [])}
    assert not forbidden_amounts & actual_amounts, result["answer"]
    normalized_answer = re.sub(r"[- ]+", " ", result["answer"].lower())
    for phrase in item["required_phrases"]:
        assert re.sub(r"[- ]+", " ", phrase) in normalized_answer, (phrase, result["answer"])


@pytest.mark.parametrize("item", with_known_gap(NOT_ANSWERABLE))
def test_pdf_abstention_and_clarification(item, pdf_answers):
    result = pdf_answers[item["question_id"]]
    assert result["status"] == item["expected_status"], result["answer"]
    assert result["citations"] == []
    assert not AMOUNT.search(result["answer"]), result["answer"]


@pytest.mark.parametrize("item", with_known_gap(ANSWERABLE))
def test_pdf_citation_accuracy(item, pdf_answers, pdf_corpus):
    result = pdf_answers[item["question_id"]]
    _, _, filenames_by_source = pdf_corpus
    assert result["status"] == "answered", result["answer"]
    for source in item["source_document_ids"]:
        assert any(citation["document"] == filenames_by_source[source]
                   and citation["page"] in item["expected_pages"]
                   and citation["section"] for citation in result["citations"]), result["citations"]
    assert all(citation["page"] in item["expected_pages"] and citation["section"]
               for citation in result["citations"])
    assert len(result["citations"]) == len({
        (citation["document"], citation["page"], citation["section"])
        for citation in result["citations"]})


@pytest.mark.parametrize("item", ANSWERABLE, ids=lambda item: item["question_id"])
def test_pdf_abstention_when_labeled_sources_lack_evidence(item, pdf_corpus):
    corpus, ids_by_source, _ = pdf_corpus
    source_ids = [ids_by_source[source] for source in item["source_document_ids"]]
    result = answer_question(
        corpus.without_evidence(source_ids), item["question"],
        context_plan_ids=source_ids, method_override="bm25", strategy_override="section_aware")
    assert result["status"] in {"insufficient_evidence", "clarification_needed"}, result["answer"]
    assert result["citations"] == []
    assert not AMOUNT.search(result["answer"]), result["answer"]
