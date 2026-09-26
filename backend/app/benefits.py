"""Conservative candidate extraction and review helpers for benefit values."""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from typing import Literal

from app.ingestion import _units, iter_table_rows

Category = Literal["deductible", "er_cost_sharing", "copay", "out_of_pocket_maximum"]


@dataclass(frozen=True)
class BenefitCandidate:
    category: Category
    value_text: str
    page_number: int
    section: str | None
    dimensions: dict[str, str]
    status: Literal["pending_review", "missing", "ambiguous"] = "pending_review"


_CATEGORY_PATTERNS: tuple[tuple[Category, re.Pattern[str]], ...] = (
    ("out_of_pocket_maximum", re.compile(r"out[- ]of[- ]pocket maximum|out[- ]of[- ]pocket limit|maximum out[- ]of[- ]pocket|payment limit", re.I)),
    ("er_cost_sharing", re.compile(r"emergency room|emergency department|emergency medical|emergency services?\b", re.I)),
    ("deductible", re.compile(r"deductible", re.I)),
    ("copay", re.compile(r"copay|co-pay|office visit|(?:primary care|specialist) visits?\b", re.I)),
)
_MONEY = re.compile(r"(?:\$\s?\d[\d,]*(?:\.\d{2})?|\d+(?:%|\s?percent)|no charge|\$?0(?:\.00)?)", re.I)
_TABLE_VALUE = re.compile(r"\$\s?\d[\d,]*(?:\.\d{1,2})?|\d+(?:\.\d+)?\s?%|no charge|no (?:annual |calendar[- ]year )?deductible|not covered|none", re.I)
# Out-of-network reimbursement schedules are not member cost sharing.
_REIMBURSEMENT = re.compile(r"amount over|\bup to\b|reimburse|allowance", re.I)
_PERIOD = re.compile(r"per\s+(calendar\s+year|year|month|visit|admission)", re.I)


def _category(text: str, *, benefit_label: bool = False) -> Category | None:
    if _CATEGORY_PATTERNS[0][1].search(text):
        return "out_of_pocket_maximum"
    if _CATEGORY_PATTERNS[1][1].search(text):
        return "er_cost_sharing"
    if benefit_label and re.search(r"\bdeductible\b", text, re.I):
        return "deductible"
    if _CATEGORY_PATTERNS[3][1].search(text):
        return "copay"
    return None


def _network(text: str) -> str | None:
    if re.search(r"out[- ]of[- ]network|outside network", text, re.I):
        return "OUT-OF-NETWORK"
    if re.search(r"in[- ]network|inside network", text, re.I):
        return "IN-NETWORK"
    return None


def _scope(text: str) -> str | None:
    if re.search(r"\bself[- ]only\b", text, re.I):
        return "individual"
    if re.search(r"\bfamily\b", text, re.I) and re.search(r"\beach member\b", text, re.I):
        return "individual"
    if re.search(r"\bfamily\b", text, re.I):
        return "family"
    if re.search(r"\bindividual\b|per person", text, re.I):
        return "individual"
    return None


def _table_candidate_rows(page: dict, carried: dict[int, tuple[list[str], str | None]] | None = None) -> list[BenefitCandidate]:
    """Recover benefit values from table rows plus nearby continuation context.

    ``carried`` maps a column count to the last column headers and row section
    seen in the document, so a table continued on the next page without its
    header row keeps its network columns and section.
    """
    candidates: list[BenefitCandidate] = []
    page_number = int(page["page_number"])
    carried = {} if carried is None else carried
    for table in page.get("tables") or []:
        active_category: Category | None = None
        active_label = ""
        active_period: str | None = None
        table_candidates: list[BenefitCandidate] = []
        headers = [str(value or "") for value in table.get("headers", [])]
        width = max((len(row) for row in table.get("rows") or []), default=0)
        continued = not any(headers) and width in carried
        row_sections = table.get("row_sections") or []
        for row_number, row_headers, row in iter_table_rows(table):
            row_section = row_sections[row_number - 1] if row_number <= len(row_sections) else None
            if any(row_headers) and len(row_headers) == width:
                carried[width] = (list(row_headers), row_section)
                continued = False
            elif continued:
                # Rows before the continued table's first heading still belong
                # to the section open at the end of the previous page.
                row_headers, carried_section = carried[width]
                row_section = carried_section or row_section
            cells = [str(value or "").strip() for value in row]
            row_text = " ".join(cell for cell in cells if cell)
            if not row_text:
                continue
            first_value_index = next((index for index, cell in enumerate(cells)
                                      if _TABLE_VALUE.search(cell)), len(cells))
            label_text = " ".join(cell for cell in cells[:first_value_index] if cell)
            found_category = _category(label_text, benefit_label=True)
            if found_category is None and re.search(r"copay|co-pay", row_text, re.I):
                found_category = "copay"
            if found_category:
                active_category = found_category
                # Keep the benefit label separate from the cost-bearing cells.
                active_label = next((cell for cell in cells
                                     if _category(cell, benefit_label=True) == found_category
                                     and not _TABLE_VALUE.search(cell)), row_text)
                active_period = None
            period_match = _PERIOD.search(row_text)
            if period_match and active_category:
                active_period = period_match.group(1).lower()
                for index, existing in enumerate(table_candidates):
                    if existing.category == active_category and existing.value_text.startswith(active_label):
                        dimensions = {**existing.dimensions, "period": active_period}
                        wording = existing.value_text
                        if f"(per {active_period})" not in wording:
                            wording += f" (per {active_period})"
                        table_candidates[index] = replace(existing, value_text=wording, dimensions=dimensions)

            category = found_category or active_category
            if category is None:
                continue
            # A continuation is associated only when it explicitly identifies
            # an individual/family amount; prose elsewhere in the table is not
            # treated as another value for the preceding benefit.
            continuation = not found_category
            row_candidates: list[BenefitCandidate] = []
            for cell_index, cell in enumerate(cells):
                if not cell:
                    continue
                if continuation and not re.search(r"\b(individual|family|per person)\b", cell, re.I):
                    continue
                matches = list(_TABLE_VALUE.finditer(cell))
                if not matches or (category == "copay" and _REIMBURSEMENT.search(cell)):
                    continue
                header = row_headers[cell_index] if cell_index < len(row_headers) else ""
                if not header and cell_index < len(headers):
                    header = headers[cell_index]
                column_network = _network(header)
                if not column_network:
                    # pdfplumber can place a value in a blank helper column
                    # beside its labeled network column; prefer the nearest
                    # explicit network header when that helper cell is empty.
                    network_headers = [(i, _network(value)) for i, value in enumerate(row_headers or headers)]
                    network_headers = [(i, value) for i, value in network_headers if value]
                    if network_headers:
                        column_network = min(network_headers, key=lambda pair: abs(pair[0] - cell_index))[1]
                for match in matches:
                    value = " ".join(match.group(0).split())
                    context = cell[max(0, match.start() - 48):min(len(cell), match.end() + 32)]
                    scope_match = re.search(r"\b(individual|family|per person)\b", context, re.I)
                    scope = (_scope(scope_match.group(1)) if scope_match
                             else _scope(header))
                    dimensions: dict[str, str] = {}
                    network = column_network or _network(row_text)
                    if network:
                        dimensions["network"] = network
                    if scope:
                        dimensions[scope] = "Individual" if scope == "individual" else "Family"
                        if scope == "individual" and re.search(r"\bfamily\b.*\beach member\b", header, re.I):
                            dimensions["family_context"] = header
                    period = active_period or (period_match.group(1).lower() if period_match else None)
                    if period:
                        dimensions["period"] = period
                    label = active_label if continuation else active_label
                    wording = f"{label}: {value}"
                    if scope:
                        wording += f" {dimensions[scope]}"
                    if period:
                        wording += f" (per {period})"
                    detected_section = row_section or page.get("section_heading")
                    if not detected_section:
                        if cells[0] and not _TABLE_VALUE.search(cells[0]):
                            detected_section = cells[0][:240]
                    if not detected_section:
                        context_headers = [value for value in row_headers or headers if value.strip() and
                                           not re.fullmatch(r"(?:in|out)[- ]of[- ]network|in[- ]network", value.strip(), re.I)]
                        detected_section = " | ".join(context_headers)[:240] or None
                    row_candidates.append(BenefitCandidate(
                        category=category, value_text=wording, page_number=page_number,
                        section=detected_section,
                        dimensions=dimensions,
                        status="pending_review"))
            # Remove repeated OCR/table cells while keeping same amounts that
            # belong to different scopes or networks.
            unique = {}
            for candidate in row_candidates:
                key = (candidate.category, candidate.value_text.casefold(), tuple(sorted(candidate.dimensions.items())))
                unique[key] = candidate
            grouped = list(unique.values())
            for candidate in grouped:
                same_context = [other for other in grouped
                                if other.category == candidate.category and other.dimensions == candidate.dimensions]
                table_candidates.append(replace(candidate, status="ambiguous") if len(same_context) > 1 else candidate)
            if found_category and not row_candidates and len(row_text) > 100:
                active_category = None
                active_label = ""
                active_period = None
        candidates.extend(table_candidates)
    return candidates


def extract_candidates(pages: list[dict]) -> list[BenefitCandidate]:
    """Find candidates with source wording, context, and provenance.

    Each page must contain ``page_number`` and ``text``; ``section_heading`` is
    optional. The source wording is preserved, and rows with multiple plausible
    values are explicitly marked ambiguous for reviewer attention.
    """
    candidates: list[BenefitCandidate] = []
    seen: set[tuple[Category, int, str]] = set()
    carried: dict[int, tuple[list[str], str | None]] = {}
    for page in pages:
        page_number = int(page["page_number"])
        table_candidates = _table_candidate_rows(page, carried)
        candidates.extend(table_candidates)
        table_categories = {candidate.category for candidate in table_candidates}
        text_sections = {unit.provenance["line"]: unit.section
                         for unit in _units([{**page, "tables": page.get("tables") or []}])
                         if not unit.table_row}
        for line_number, raw_line in enumerate(str(page.get("text", "")).splitlines(), 1):
            line = " ".join(raw_line.split())
            if not line:
                continue
            category = _category(line, benefit_label=True)
            if category == "deductible" and re.search(r"after deductible|deductible waived", line, re.I):
                category = None
            if category is None or category in table_categories:
                continue
            values = _MONEY.findall(line)
            if not values:
                continue
            key = (category, page_number, line.casefold())
            if key in seen:
                continue
            seen.add(key)
            dimensions = {}
            for label, pattern in (("network", r"in[- ]network|out[- ]of[- ]network"), ("family", r"family"), ("individual", r"individual|per person"), ("coinsurance", r"coinsurance|after the deductible")):
                match = re.search(pattern, line, re.I)
                if match:
                    dimensions[label] = match.group(0)
            normalized_values = {value.lower().replace(" ", "").replace(",", "") for value in values}
            candidates.append(BenefitCandidate(
                category=category,
                value_text=line,
                page_number=page_number,
                section=text_sections.get(line_number) or page.get("section_heading"),
                dimensions=dimensions,
                status="ambiguous" if len(normalized_values) > 1 else "pending_review",
            ))
    return candidates
