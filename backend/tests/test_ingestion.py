from contextlib import contextmanager

import pytest

from app import ingestion
from app.benefits import extract_candidates
from app.ingest import _section_heading
from app.ingestion import build_chunks, parse_pdf


def test_table_rows_remain_whole_and_keep_headers_in_both_strategies():
    pages = [{
        "page_number": 2,
        "text": "BENEFITS\nThe details below apply to the plan.",
        "tables": [{
            "headers": ["Service", "What you pay"],
            "rows": [["Emergency room", "$250 copay and 20% coinsurance"],
                     ["Long row", "x" * 1400]],
        }],
    }]

    chunks = build_chunks(pages)
    expected = {(2, 1, 1), (2, 1, 2)}
    for strategy_chunks in chunks.values():
        actual = {
            (unit["page"], unit["table_number"], unit["row_number"])
            for chunk in strategy_chunks
            for unit in chunk["provenance"]["units"]
            if unit["kind"] == "table_row"
        }
        assert actual == expected
        table_chunk_text = "\n".join(chunk["text"] for chunk in strategy_chunks)
        assert "Table headers: Service | What you pay" in table_chunk_text
        assert "Service: Emergency room" in table_chunk_text
        assert "x" * 1400 in table_chunk_text


def test_section_aware_chunks_preserve_section_provenance_when_available():
    chunks = build_chunks([{
        "page_number": 1,
        "text": "COST SHARING\nDeductible: $500\nWHAT IS NOT COVERED\nCosmetic services",
        "tables": [],
    }])

    section_chunks = chunks["section_aware"]
    assert len(section_chunks) == 2
    assert section_chunks[0]["provenance"]["units"][0]["section"] == "COST SHARING"
    assert section_chunks[1]["provenance"]["units"][0]["section"] == "WHAT IS NOT COVERED"


def test_chunks_keep_missing_section_provenance_unknown():
    chunks = build_chunks([{
        "page_number": 4,
        "text": "A paragraph without a detectable heading.",
        "tables": [],
    }])

    assert chunks["section_aware"][0]["provenance"]["units"][0]["section"] is None


def test_page_section_is_unknown_when_page_has_multiple_headings():
    assert _section_heading("PLAN DESIGN & BENEFITS\nEMERGENCY MEDICAL CARE\nEmergency Room $100") is None
    assert _section_heading("EMERGENCY MEDICAL CARE\nEmergency Room $100") == "EMERGENCY MEDICAL CARE"


def test_parse_pdf_rejects_malformed_input():
    with pytest.raises(Exception):
        parse_pdf(b"not a PDF")


def test_parse_keeps_rows_before_and_at_a_later_header(monkeypatch):
    class Page:
        def extract_text(self):
            return "DENTAL BENEFITS"

        def extract_tables(self):
            return [[
                ["", "Dental plan title", None],
                ["What does the plan cover?", "Details about benefits", None],
                ["", "In Network", "Out of Network"],
                ["Deductible", "$50", "$100"],
            ]]

    @contextmanager
    def fake_pdf(_bytes):
        yield type("PDF", (), {"pages": [Page()]})()

    monkeypatch.setattr(ingestion.pdfplumber, "open", fake_pdf)
    pages = parse_pdf(b"%PDF-test")
    table = pages[0]["tables"][0]
    assert table["header_row_index"] == 2
    assert len(table["rows"]) == 4
    units = [unit for chunk in build_chunks(pages)["section_aware"]
             for unit in chunk["provenance"]["units"] if unit["kind"] == "table_row"]
    assert [unit["row_number"] for unit in units] == [1, 2, 3, 4]
    assert units[0]["headers"] == []
    assert units[-1]["headers"] == ["", "In Network", "Out of Network"]


def test_parse_removes_repeated_value_from_unheaded_helper_column(monkeypatch):
    class Page:
        def extract_text(self):
            return "PLAN FEATURES"

        def extract_tables(self):
            return [[
                ["", "PLAN FEATURES", "", "", "IN-NETWORK", ""],
                ["", "Out-of-Pocket Maximum", "", "$2,500 Individual", "$2,500 Individual", ""],
            ]]

    @contextmanager
    def fake_pdf(_bytes):
        yield type("PDF", (), {"pages": [Page()]})()

    monkeypatch.setattr(ingestion.pdfplumber, "open", fake_pdf)
    table = parse_pdf(b"%PDF-test")[0]["tables"][0]
    assert table["rows"][1] == ["", "Out-of-Pocket Maximum", "", "", "$2,500 Individual", ""]
    assert table["raw_rows"][1][3] == "$2,500 Individual"


def test_table_rows_follow_page_position_and_keep_their_own_section(monkeypatch):
    class Table:
        bbox = (0, 20, 200, 80)
        rows = [type("Row", (), {"bbox": (0, top, 200, top + 10)})()
                for top in (25, 45)]

        def extract(self):
            return [["Service", "What you pay"], ["Deductible", "$500"]]

    class Page:
        def extract_text(self):
            return "COST SHARING\nService What you pay\nDeductible $500\nOTHER SERVICES"

        def extract_text_lines(self):
            return [
                {"text": value, "x0": 10, "x1": 150, "top": top, "bottom": top + 8}
                for value, top in (("COST SHARING", 10), ("Service What you pay", 25),
                                   ("Deductible $500", 45), ("OTHER SERVICES", 100))
            ]

        def find_tables(self):
            return [Table()]

    @contextmanager
    def fake_pdf(_bytes):
        yield type("PDF", (), {"pages": [Page()]})()

    monkeypatch.setattr(ingestion.pdfplumber, "open", fake_pdf)
    pages = parse_pdf(b"%PDF-test")
    units = [unit for chunk in build_chunks(pages)["section_aware"]
             for unit in chunk["provenance"]["units"]]

    assert pages[0]["tables"][0]["row_sections"] == ["COST SHARING", "COST SHARING"]
    assert [unit["kind"] for unit in units] == ["text", "table_row", "table_row", "text"]
    assert units[-1]["section"] == "OTHER SERVICES"
    assert extract_candidates(pages)[0].section == "COST SHARING"
