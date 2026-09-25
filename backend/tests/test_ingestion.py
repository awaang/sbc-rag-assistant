from contextlib import contextmanager

import pytest

from app import ingestion
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
