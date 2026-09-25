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
    return (line.isupper() or bool(re.match(r"^\d+(?:\.\d+)*\s+[A-Z]", line))
            or bool(re.search(r"\bYou Pay$", line))
            or line in {"Accumulation Period", "Out-of-Pocket Maximum(s) and Deductible(s)"})


def _header_index(rows: list[list[str]]) -> int | None:
    """Recognize a short column-label row; retain every raw row regardless."""
    best: tuple[int, int] | None = None
    for index, row in enumerate(rows[:5]):
        cells = [cell for cell in row if cell]
        if len(cells) < 2 or max(map(len, cells)) > 100 or any("?" in cell for cell in cells):
            continue
        score = sum(bool(re.search(r"\b(network|coverage|benefits|features|amounts|pay)\b", cell, re.I))
                    for cell in cells)
        if score and (best is None or score > best[0]):
            best = (score, index)
    return best[1] if best else None


def _remove_headerless_adjacent_duplicates(rows: list[list[str]], header_index: int | None) -> list[list[str]]:
    """Drop a duplicated cell only when the duplicate sits beside its labeled column."""
    if header_index is None:
        return rows
    headers = rows[header_index]
    cleaned = [list(row) for row in rows]
    for row_index, row in enumerate(cleaned):
        if row_index <= header_index:
            continue
        for index in range(1, min(len(row), len(headers))):
            if (row[index] and row[index] == row[index - 1]
                    and headers[index] and not headers[index - 1]):
                row[index - 1] = ""
    return cleaned


def iter_table_rows(table: dict[str, Any]):
    """Carry explicit column context through a table and its section headers."""
    header_index = table.get("header_row_index")
    active_headers: list[str] = list(table.get("headers") or []) if header_index in (None, 0) else []
    for index, row in enumerate(table["rows"]):
        is_header = index == header_index and row == table.get("headers")
        if is_header:
            active_headers = row
        elif _table_heading(row) and any(
                re.fullmatch(r"(?:in|out)[- ]of[- ]network|in[- ]network", cell, re.I)
                for cell in row if cell):
            active_headers = row
        headers = [] if is_header else active_headers
        yield index + 1, headers, row


def _table_heading(row: list[str]) -> str | None:
    """Use an explicit table section row, not a cost or network value, as context."""
    cells = [cell for cell in row if cell]
    if not cells:
        return None
    heading = cells[0]
    if re.fullmatch(r"(?:in|out)[- ]of[- ]network|in[- ]network", heading, re.I):
        return None
    if not _is_heading(heading) or re.search(r"\d|\b(covered|copay|coinsurance)\b", heading, re.I):
        return None
    if len(heading) < 5 or heading.startswith("("):
        return None
    if any(not re.fullmatch(r"(?:in|out)[- ]of[- ]network|in[- ]network", cell, re.I)
           for cell in cells[1:]):
        return None
    return heading


def _line_inside_table(line: dict[str, Any], table: dict[str, Any]) -> bool:
    bbox = table.get("bbox")
    if not bbox:
        return False
    x0, top, x1, bottom = bbox
    mid_x = (line["x0"] + line["x1"]) / 2
    mid_y = (line["top"] + line["bottom"]) / 2
    return x0 <= mid_x <= x1 and top <= mid_y <= bottom


def parse_pdf(pdf_bytes: bytes) -> list[dict[str, Any]]:
    """Return page text and table cells without discarding table structure."""
    parsed: list[dict[str, Any]] = []
    with pdfplumber.open(BytesIO(pdf_bytes)) as pdf:
        for page_number, page in enumerate(pdf.pages, 1):
            try:
                raw_text = page.extract_text() or ""
            except Exception as exc:
                parsed.append({"page_number": page_number, "text": "", "tables": [],
                               "parse_error": f"Page {page_number} text extraction failed: {type(exc).__name__}: {exc}"[:500]})
                continue
            tables = []
            table_error = None
            try:
                found_tables = page.find_tables() if hasattr(page, "find_tables") else None
                source_tables = found_tables if found_tables is not None else (page.extract_tables() or [])
            except Exception as exc:
                found_tables, source_tables = None, []
                table_error = f"Page {page_number} table extraction failed: {type(exc).__name__}: {exc}"[:500]
            for source_table in source_tables:
                try:
                    raw_table = source_table.extract() if found_tables is not None else source_table
                    rows = [[_clean_cell(cell) for cell in row] for row in raw_table]
                except Exception as exc:
                    table_error = f"Page {page_number} table extraction failed: {type(exc).__name__}: {exc}"[:500]
                    continue
                kept = [(index, row) for index, row in enumerate(rows) if any(row)]
                rows = [row for _, row in kept]
                if not rows:
                    continue
                header_index = _header_index(rows)
                raw_rows = rows
                rows = _remove_headerless_adjacent_duplicates(rows, header_index)
                table = {"headers": rows[header_index] if header_index is not None else [],
                         "header_row_index": header_index if header_index is not None else -1,
                         "rows": rows}
                if rows != raw_rows:
                    table["raw_rows"] = raw_rows
                if found_tables is not None:
                    table["bbox"] = list(source_table.bbox)
                    table["row_tops"] = [source_table.rows[index].bbox[1] for index, _ in kept]
                tables.append(table)
            text_lines = None
            if hasattr(page, "extract_text_lines"):
                try:
                    text_lines = [{"text": line["text"], "x0": line["x0"], "x1": line["x1"],
                                   "top": line["top"], "bottom": line["bottom"]}
                                  for line in page.extract_text_lines()]
                    if not text_lines and raw_text.strip():
                        text_lines = None
                except Exception:
                    text_lines = None
            record = {"page_number": page_number, "text": raw_text, "tables": tables}
            if table_error:
                record["table_error"] = table_error
            if text_lines is not None:
                record["text_lines"] = text_lines
            row_sections = {(unit.provenance["table_number"], unit.provenance["row_number"]): unit.section
                            for unit in _units([record]) if unit.table_row}
            for table_number, table in enumerate(tables, 1):
                table["row_sections"] = [row_sections.get((table_number, row_number))
                                         for row_number in range(1, len(table["rows"]) + 1)]
            parsed.append(record)
    if not parsed:
        raise ValueError("The PDF contains no pages.")
    return parsed


def _units(pages: list[dict[str, Any]]) -> list[Unit]:
    units: list[Unit] = []
    for page in pages:
        page_number = page["page_number"]
        section: str | None = None
        events: list[tuple[float, int, int, str, Any]] = []
        text_lines = page.get("text_lines")
        if text_lines is None:
            text_lines = [{"text": line} for line in page["text"].splitlines()]
        for line_number, line in enumerate(text_lines, 1):
            if "top" in line and any(_line_inside_table(line, table) for table in page["tables"]):
                continue
            events.append((float(line.get("top", line_number)), 0, line_number, "text", line["text"]))
        for table_number, table in enumerate(page["tables"], 1):
            for row_number, headers, row in iter_table_rows(table):
                tops = table.get("row_tops") or []
                top = tops[row_number - 1] if row_number <= len(tops) else len(text_lines) + table_number + row_number / 1000
                events.append((float(top), 1, table_number, "table", (table_number, row_number, headers, row)))
        for _, _, index, kind, payload in sorted(events):
            if kind == "text":
                line = " ".join(payload.split())
                if not line:
                    continue
                if _is_heading(line):
                    section = line
                units.append(Unit(line, page_number, section, {"kind": "text", "line": index,
                                                              "text": line}))
                continue
            table_number, row_number, headers, row = payload
            section = _table_heading(row) or section
            header_text = " | ".join(headers)
            cells = [f"{headers[i] if i < len(headers) and headers[i] else f'Column {i + 1}'}: {cell}" for i, cell in enumerate(row) if cell]
            if not cells:
                continue
            rendered = (f"Table headers: {header_text}\n" if header_text else "") + " | ".join(cells)
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
