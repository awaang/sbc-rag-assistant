from pathlib import Path

import pytest

from app.benefits import extract_candidates
from app.ingestion import build_chunks, parse_pdf


@pytest.fixture(scope="module")
def kaiser_connection():
    """Real SBC PDF parsing/extraction; only database access is replaced."""
    source_pdf = (Path(__file__).resolve().parents[2] /
                  "data/source-documents/received/Kaiser HMO Plan Summary 2017.pdf")
    pages = parse_pdf(source_pdf.read_bytes())
    plan = {"plan_id": 1, "insurer": "Kaiser Permanente", "plan_name": "Traditional Plan",
            "plan_type": "hmo", "coverage_type": "medical", "plan_year": 2017}
    chunks = [{"chunk_id": index, "document_id": 1, "plan_id": 1,
               "plan_name": plan["plan_name"], "original_filename": source_pdf.name,
               "chunk_text": chunk["text"], "page_start": chunk["page_start"],
               "page_end": chunk["page_end"], "provenance": chunk["provenance"]}
              for index, chunk in enumerate(build_chunks(pages)["section_aware"], 1)]
    benefits = [{"benefit_id": index, "plan_id": 1, "category": candidate.category,
                 "value_text": candidate.value_text, "dimensions": candidate.dimensions,
                 "verification_status": candidate.status, "reviewed_at": None,
                 "source_section_verified": False, "section": candidate.section,
                 "page_number": candidate.page_number, "parse_status": "parsed",
                 "document_id": 1, "original_filename": source_pdf.name,
                 "plan_name": plan["plan_name"]}
                for index, candidate in enumerate(extract_candidates(pages), 1)]

    class Result:
        def __init__(self, rows):
            self.rows = rows

        def fetchall(self):
            return self.rows

    class Connection:
        def execute(self, sql, params=()):
            if "FROM plans p JOIN documents" in sql:
                return Result([plan])
            if "FROM benefit_records b" in sql:
                return Result([row for row in benefits if row["category"] == params[1]])
            if "FROM chunks c JOIN documents d" in sql:
                return Result(chunks)
            raise AssertionError(sql)

    return Connection()
