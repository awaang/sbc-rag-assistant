"""Table-aware PDF parsing and row-preserving chunk construction."""

from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
import re
from typing import Any

import pdfplumber

CHUNK_SIZE = 1200


@dataclass(frozen=True)
class Unit:
    text: str
    page_number: int
    section: str | None
    provenance: dict[str, Any]
    table_row: bool = False


def _clean_cell(value: Any) -> str:
    return " ".join(str(value or "").split())


def _is_heading(line: str) -> bool:
    if not line or len(line) > 120 or re.search(r"[.$%]", line):
        return False
    return line.isupper() or bool(re.match(r"^\d+(?:\.\d+)*\s+[A-Z]", line))


def parse_pdf(pdf_bytes: bytes) -> list[dict[str, Any]]:
    """Return page text and table cells without discarding table structure."""
    parsed: list[dict[str, Any]] = []
    with pdfplumber.open(BytesIO(pdf_bytes)) as pdf:
        for page_number, page in enumerate(pdf.pages, 1):
            raw_text = page.extract_text() or ""
            tables = []
            for raw_table in page.extract_tables() or []:
                rows = [[_clean_cell(cell) for cell in row] for row in raw_table]
                rows = [row for row in rows if any(row)]
                if not rows:
                    continue
                tables.append({"headers": rows[0], "rows": rows[1:]})
            parsed.append({"page_number": page_number, "text": raw_text, "tables": tables})
    if not parsed:
        raise ValueError("The PDF contains no pages.")
    return parsed


def _units(pages: list[dict[str, Any]]) -> list[Unit]:
    units: list[Unit] = []
    for page in pages:
        page_number = page["page_number"]
        section: str | None = None
        for line_number, raw_line in enumerate(page["text"].splitlines(), 1):
            line = " ".join(raw_line.split())
            if not line:
                continue
            if _is_heading(line):
                section = line
            units.append(Unit(line, page_number, section, {"kind": "text", "line": line_number}))
        for table_number, table in enumerate(page["tables"], 1):
            headers = table["headers"]
            header_text = " | ".join(headers)
            for row_number, row in enumerate(table["rows"], 1):
                cells = [f"{headers[i] if i < len(headers) and headers[i] else f'Column {i + 1}'}: {cell}" for i, cell in enumerate(row) if cell]
                if not cells:
                    continue
                rendered = f"Table headers: {header_text}\n" + " | ".join(cells)
                units.append(Unit(rendered, page_number, section, {
                    "kind": "table_row", "table_number": table_number,
                    "row_number": row_number, "headers": headers, "cells": row,
                }, True))
    return units


def build_chunks(pages: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    """Pack text units to a target size, keeping each table row indivisible."""
    units = _units(pages)
    result: dict[str, list[dict[str, Any]]] = {"fixed_size": [], "section_aware": []}
    for strategy in result:
        groups: list[list[Unit]] = []
        current: list[Unit] = []
        current_size = 0
        current_section: str | None = None
        for unit in units:
            size = len(unit.text)
            section_boundary = strategy == "section_aware" and current and unit.section != current_section
            if current and (current_size + size > CHUNK_SIZE or section_boundary):
                groups.append(current)
                current, current_size = [], 0
            current.append(unit)
            current_size += size
            current_section = unit.section
        if current:
            groups.append(current)
        for group in groups:
            result[strategy].append({
                "text": "\n".join(unit.text for unit in group),
                "page_start": min(unit.page_number for unit in group),
                "page_end": max(unit.page_number for unit in group),
                "provenance": {"units": [
                    {"page": unit.page_number, "section": unit.section, **unit.provenance}
                    for unit in group
                ]},
            })
    return result
