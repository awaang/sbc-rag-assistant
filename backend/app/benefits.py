"""Conservative candidate extraction and review helpers for benefit values."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

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
    ("out_of_pocket_maximum", re.compile(r"out[- ]of[- ]pocket maximum|out[- ]of[- ]pocket limit|maximum out[- ]of[- ]pocket", re.I)),
    ("er_cost_sharing", re.compile(r"emergency room|emergency department|emergency medical", re.I)),
    ("deductible", re.compile(r"deductible", re.I)),
    ("copay", re.compile(r"copay|co-pay|office visit", re.I)),
)
_MONEY = re.compile(r"(?:\$\s?\d[\d,]*(?:\.\d{2})?|\d+(?:%|\s?percent)|no charge|\$?0(?:\.00)?)", re.I)


def extract_candidates(pages: list[dict]) -> list[BenefitCandidate]:
    """Find source lines worth human review; never promote these to verified facts.

    Each page must contain ``page_number`` and ``text``; ``section_heading`` is
    optional. The source wording is preserved, and rows with multiple plausible
    values are explicitly marked ambiguous for reviewer attention.
    """
    candidates: list[BenefitCandidate] = []
    seen: set[tuple[Category, int, str]] = set()
    for page in pages:
        page_number = int(page["page_number"])
        for raw_line in str(page.get("text", "")).splitlines():
            line = " ".join(raw_line.split())
            if not line:
                continue
            category = next((kind for kind, pattern in _CATEGORY_PATTERNS if pattern.search(line)), None)
            if category is None:
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
                section=page.get("section_heading"),
                dimensions=dimensions,
                status="ambiguous" if len(normalized_values) > 1 else "pending_review",
            ))
    return candidates
