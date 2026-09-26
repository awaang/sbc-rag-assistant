"""Audit text retention in both chunk strategies for every SBC PDF page."""

import hashlib
import json
import re
from collections import Counter
from pathlib import Path

import pytest

from app.ingestion import build_chunks, parse_pdf


ROOT = Path(__file__).resolve().parents[2] / "data/source-documents/received"
DOCUMENTS = json.loads((ROOT / "metadata.json").read_text())["documents"]


def words(text):
    return Counter(re.findall(r"[a-z0-9]+", text.lower()))


@pytest.mark.parametrize("document", DOCUMENTS, ids=lambda document: document["document_id"])
def test_every_extracted_line_is_retained_in_cited_chunks(document):
    source = (ROOT / document["relative_path"]).read_bytes()
    assert hashlib.sha256(source).hexdigest() == document["sha256"]
    pages = parse_pdf(source)
    chunks_by_strategy = build_chunks(pages)
    for strategy, chunks in chunks_by_strategy.items():
        units = [unit for chunk in chunks for unit in chunk["provenance"]["units"]]
        for page in pages:
            page_units = [unit for unit in units if unit["page"] == page["page_number"]]
            evidence = words(" ".join(
                " ".join(unit["cells"]) if unit["kind"] == "table_row" else unit["text"]
                for unit in page_units))
            assert not words(page["text"]) - evidence, (
                document["original_filename"], page["page_number"], strategy,
                words(page["text"]) - evidence)
            unit_words = [words(" ".join(unit["cells"]) if unit["kind"] == "table_row"
                                else unit["text"]) for unit in page_units]
            for line_number, line in enumerate(page["text"].splitlines(), 1):
                line_words = words(line)
                if not line_words:
                    continue
                overlap = max((sum((line_words & candidate).values()) / sum(line_words.values())
                               for candidate in unit_words), default=0)
                assert overlap >= 0.6, (
                    document["original_filename"], page["page_number"], line_number,
                    strategy, line)
