"""Complete, cited source passages built from document structure, not question templates."""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field, replace
from difflib import get_close_matches
import re

from app.retrieval import tokenize

# These are vocabulary equivalents, not plan facts or answer values.
ALIASES = (
    (r"\bout[ -]of[ -]pocket(?: (?:maximums?|limits?))?|\bpayment limits?\b|\boop(?: max)?\b", "oop"),
    (r"\bemergency (?:room|department|services?)\b|\ber\b", "emergency"),
    (r"\bprimary care physician|\bpcp\b", "primary care"),
    (r"\b(?:hospitalization|hospitalisation)|\bhospital (?:stay|admission)|\binpatient (?:hospital|coverage)", "inpatient hospital"),
    (r"\bchemical dependency|\bsubstance abuse", "addiction"),
    (r"\bspinal manipulation|\bmanipulative therapy|\bchiropractic care|\bchiropractor", "chiropractic"),
    (r"\bmental health|\bpsychiatric", "mental"),
    (r"\bbrand[ -]name", "brand"),
    (r"\bmail[ -]order|\bhome delivery", "mailorder"),
    (r"\bx[ -]?rays?", "xray"),
    (r"\blabs?\b|\blaboratory tests?", "laboratory"),
    (r"\bimmunizations?|\bvaccinations?|\bvaccines?", "vaccine"),
    (r"\bbraces\b|\borthodontics?", "orthodontia"),
    (r"\bcheckups?\b", "exams"),
    (r"\bdeductable", "deductible"),
    (r"\bco[ -]pay", "copay"),
    (r"\bphysiotherapy", "physical therapy"),
    (r"\bdme\b", "durable medical equipment"),
)
IGNORE = set("a an the what how when where which who why is are was were be been am do does did can could would will should i me my we our you your they their it its this that these those for from under in on at to of by with and or if as per about does have has get getting need much many pay paying paid pays cost costs charge charges copay copays coinsurance coverage covered cover covers plan plans benefit benefits summary say says tell please show give include includes including apply applies applicable available services service treatment treatments price prices all most there any also both compare comparison versus vs between across provided member members during regarding amount amounts detail details information explain listed list limit limits often year years visit visits calendar per year annual once twice three two one dollar dollars percent percentage maximum minimum whether through concerning reimbursed reimbursement information insured insurance medically necessary".split())
IGNORE.update("s out network individual family self only patient happen happens meet meeting according over care innetwork outofnetwork day days supply yearly annually".split())
IGNORE.difference_update({"medically", "necessary"})
GENERIC_SECTIONS = {"", "employees", "plan design benefits", "provided by aetna life insurance company", "summary of benefits", "benefit summary"}
GROUP = re.compile(r"^(?:Generic Drugs|(?:Non-)?Preferred Brand-Name Drugs|Premier Specialty Drugs|Pharmacy Day Supply and Requirements|Contact Lenses|Lenses|Co-Pay)$", re.I)
VALUE = re.compile(r"\$|\d\s*%|\b(?:none|no charge|covered|not covered|not available|not applicable|waived|required|optional|unlimited|copay|cost sharing|cost share|see |refer |up to|amount over|discount|not waived|once|twice)\b", re.I)
META = re.compile(r"^(?:Page \d+|(?:Pr)?oduced on |\d{6,}[.]|©|DAHLIN GROUP|Effective Date|PROVIDED BY |PLAN DESIGN|HMO - California|Open Access|Summary of Benefits|Benefit Summary|Principal Benefits|Kaiser Permanente Traditional Plan \(|Dental Benefit Summary|Vision Benefit Summary)$", re.I)


def clean(value: str) -> str:
    return " ".join(value.split())


def terms(text: str) -> set[str]:
    text = text.lower()
    for pattern, replacement in ALIASES:
        text = re.sub(pattern, replacement, text)
    return {word[:-3] + "y" if word.endswith("ies") else
            word[:-1] if len(word) > 3 and word.endswith("s") and not word.endswith(("ss", "us", "is")) else word
            for word in tokenize(text) if word not in (IGNORE - {"coinsurance", "maximum", "copay"})} - (IGNORE - {"coinsurance", "maximum", "copay"})


@dataclass
class Passage:
    document_id: int
    plan_name: str
    filename: str
    page: int
    section: str
    label: str
    kind: str
    units: list[dict] = field(default_factory=list)
    chunk_ids: set[int] = field(default_factory=set)
    headers: list[str] = field(default_factory=list)
    rows: list[list[str]] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    context: str = ""

    @property
    def wording(self) -> str:
        columns = []
        if self.rows:
            width = max(map(len, self.rows))
            for i in range(width):
                values = [row[i] for row in self.rows if i < len(row) and row[i]]
                value = clean(" ".join(dict.fromkeys(values)))
                if not value:
                    continue
                header = self.headers[i] if i < len(self.headers) else ""
                if not header:
                    network_headers = [(j,h) for j,h in enumerate(self.headers) if re.search(r"network", h, re.I)]
                    if network_headers and i >= min(j for j,_ in network_headers) - 1:
                        header = min(network_headers, key=lambda pair: abs(pair[0]-i))[1]
                columns.append(f"{header}: {value}" if header and header != value else value)
        else:
            columns.append(self.label)
        return clean(" | ".join(columns) + " " + " ".join(self.notes))

    @property
    def search_text(self) -> str:
        return f"{self.context} {self.section} {self.label} {self.wording}"

    @property
    def citation(self) -> dict:
        return {"plan": self.plan_name, "document": self.filename, "page": self.page, "section": self.section or self.label}


def _unit_text(unit):
    return clean(" ".join(unit.get("cells", [])) if unit["kind"] == "table_row" else unit.get("text", ""))


def _metadata(text):
    return bool(META.match(text) or re.match(r"^(?:Page \d+|(?:Pr)?oduced on |\d{6,}[.]|©|DAHLIN GROUP|Effective Date|PROVIDED BY |Open Access.*California|Kaiser Permanente Traditional Plan \()", text, re.I))


def _section(section, label):
    return label if " ".join(tokenize(section or "")) in GENERIC_SECTIONS else section or label


def build_catalog(chunks: list[dict]) -> list[Passage]:
    """Join value-cell continuations and notes up to the next source row/heading.

    Only supplied approved chunk provenance is used. Headers may carry across a
    page in the same document. Every joined line retains its own source locator.
    """
    docs = defaultdict(list)
    seen = set()
    for chunk in chunks:
        for unit in (chunk.get("provenance") or {}).get("units", []):
            key = (chunk.get("document_id"), unit.get("page"), unit.get("kind"),
                   unit.get("table_number"), unit.get("row_number"), unit.get("line"), _unit_text(unit))
            if key not in seen:
                seen.add(key)
                docs[chunk.get("document_id", 0)].append((chunk, unit))
    cards = []
    for doc, items in docs.items():
        current = None
        group = ""
        inherited_headers = []
        payer_headers = []
        last_page = None
        narrative = None
        for chunk, unit in items:
            text = _unit_text(unit)
            if not text or unit["kind"] == "raw_line" or _metadata(text):
                continue
            page = unit.get("page")
            if page != last_page:
                current = narrative = None
                group = ""
                last_page = page
            def start(label, kind, headers=None, rows=None, context=""):
                card = Passage(doc, chunk["plan_name"], chunk["original_filename"], page,
                               _section(unit.get("section"), label), label, kind,
                               [unit], {chunk["chunk_id"]}, headers or [], rows or [], [], context)
                cards.append(card)
                return card
            def attach(card, note=None, row=None):
                card.units.append(unit)
                card.chunk_ids.add(chunk["chunk_id"])
                if row is not None:
                    card.rows.append(row)
                elif note and note not in card.wording:
                    card.notes.append(note)
            if unit["kind"] == "table_row":
                cells = [clean(x) for x in unit.get("cells", [])]
                headers = list(unit.get("headers") or [])
                if cells == headers:
                    inherited_headers = headers
                    current = narrative = None
                    continue
                effective_headers = headers or inherited_headers
                # Keep positions while removing duplicate geometric cells.
                nonempty = [(i, c) for i, c in enumerate(cells) if c]
                for (i, c), (j, d) in zip(nonempty, nonempty[1:]):
                    if c == d and not (i < len(effective_headers) and effective_headers[i]):
                        cells[i] = ""
                nonempty = [(i, c) for i, c in enumerate(cells) if c]
                networks = [(i, c) for i, c in nonempty if re.fullmatch(r"(?:in|inside|out of|out-of)[ -]?network", c, re.I)]
                if networks:
                    inherited_headers = cells
                    if payer_headers:
                        inherited_headers = [f"{h} — {payer_headers[i]}" if h and i < len(payer_headers) and payer_headers[i] else h
                                             for i,h in enumerate(inherited_headers)]
                    current = narrative = None
                    group = ""
                    continue
                if headers and any(re.search(r"network|self.only|family coverage", h, re.I) for h in headers):
                    inherited_headers = headers
                if cells == headers or (text == (unit.get("section") or "") and len(nonempty) == 1):
                    current = narrative = None
                    group = ""
                    continue
                label_index, label = nonempty[0]
                if label.startswith("How much does the plan pay"):
                    payer_headers = cells
                    inherited_headers = [f"{h} — {cells[i]}" if i < len(cells) and cells[i] else h
                                         for i,h in enumerate(inherited_headers)]
                    current = narrative = None
                    continue
                if label.startswith("Plan Includes:"):
                    current = None
                    group = ""
                # Multi-column cost tables can omit the label on continuation rows.
                value_start = min((i for i,h in enumerate(inherited_headers)
                                   if re.search(r"network|self.only|family coverage|you pay", h, re.I)), default=99)
                continuation = label_index >= value_start or bool(re.match(r"^(?:\$|\d+%|None Family|Maximum \$)", label))
                if continuation and current and current.kind == "benefit":
                    if label in current.wording:
                        continue
                    attach(current, row=cells)
                    continue
                if GROUP.fullmatch(label) and len(nonempty) == 1:
                    current = narrative = None
                    group = label
                    continue
                if len(nonempty) >= 2 and not continuation and any(len(v) > 1 for _,v in nonempty[1:]):
                    # A real label/value row, even if the value is a referral or condition.
                    title = f"{group} — {label}" if group else label
                    if all(re.fullmatch(r"(?:Not )?Waived", v, re.I) for _,v in nonempty[1:]):
                        title = f"Deductible — {label}"
                    if group == "Contact Lenses" and label in {"Frames", "Lens & Frame Allowance", "Cosmetic Extras", "Laser correction surgery"}:
                        group = ""; title = label
                    row_headers = list(inherited_headers)
                    # A page may add empty geometric columns within the same two-column table.
                    if len(row_headers) == 2 and len(cells) > 2:
                        row_headers = [row_headers[0]] + [""] * (len(cells)-2) + [row_headers[1]]
                    current = start(title, "benefit", row_headers, [cells], group)
                    narrative = None
                    continue
                if current and current.kind == "benefit" and unit.get("section") in {current.section, None, "PLAN DESIGN & BENEFITS", "EMPLOYEES", "PROVIDED BY AETNA LIFE INSURANCE COMPANY"}:
                    if len(nonempty) == 2 and len(nonempty[1][1]) == 1:
                        text = nonempty[0][1] + nonempty[1][1]
                    attach(current, note=text)
                    continue
            else:
                if text == unit.get("section"):
                    current = narrative = None
                    group = ""
                    continue
                if re.search(r"\.{3,}|…{2,}", text):
                    label = re.split(r"\.{3,}|…{2,}", text, maxsplit=1)[0].strip()
                    current = start(label, "benefit")
                    current.notes = [text[len(label):].strip()]
                    narrative = None
                    continue
                if current and current.kind == "benefit" and unit.get("section") == current.section and not text.startswith("This is a summary"):
                    attach(current, note=text)
                    continue
            # Free text, including long exclusions, remains searchable as paragraphs.
            if narrative and narrative.page == page and not re.match(r"^[•●]|^(?:The |This |Your |For |In case|Aetna |Laser |Important |Definitions |\d+ Restrictions)", text):
                attach(narrative, note=text)
            else:
                narrative = start(text, "narrative")
            current = None
        # Exclusions are qualified by their document's actual introductory text.
        qualifiers = [c for c in cards if c.document_id == doc and
                      ("generally not covered" in c.wording or "plan does not pay for" in c.wording)]
        for card in cards:
            if card.document_id != doc:
                continue
            if card.label.startswith(("•", "●")) and qualifiers:
                card.kind = "exclusion"
                card.context = " ".join(c.wording for c in qualifiers)
    return cards


def query_terms(question: str, plan_names: list[str], vocabulary: set[str]) -> tuple[set[str], dict[str, str]]:
    q = question
    q = re.sub(r"\bDentalGuard (?:Preferred|Pref)(?: PPO)?", " ", q, flags=re.I)
    for name in sorted(plan_names, key=len, reverse=True):
        q = re.sub(re.escape(name), " ", q, flags=re.I)
    plan_tokens = set().union(*(set(tokenize(name)) for name in plan_names)) - {
        "health", "group", "care", "medical", "dental", "vision", "basic", "preferred",
        "choice", "managed", "open", "access", "plan", "summary", "benefit", "benefits"}
    q = " ".join(word for word in q.split() if word.lower().strip("?,.") not in plan_tokens)
    # Network/scope constrain evidence rather than identify the service.
    q = re.sub(r"\b(?:in[- ]network|out[- ]of[- ]network|individual|family|self[- ]only)\b", " ", q, flags=re.I)
    wanted = terms(q)
    corrections = {}
    for word in wanted - vocabulary:
        if len(word) >= 5:
            near = get_close_matches(word, vocabulary, n=2, cutoff=.84)
            if len(near) == 1:
                corrections[word] = near[0]
    return {corrections.get(word, word) for word in wanted}, corrections


def select_passages(cards: list[Passage], question: str, plan_names: list[str]) -> tuple[list[Passage], dict]:
    """Require all requested subject words; rank only source-backed passages."""
    if not cards:
        return [], {"reason": "no_source_passages"}
    vocabulary = set().union(*(terms(c.search_text) for c in cards))
    wanted, corrections = query_terms(question, plan_names, vocabulary)
    wanted -= {"exclusion", "exclusions", "exclude", "excluded", "covered", "cover", "doesnt", "doesn"}
    if not wanted:
        return [], {"reason": "no_service_requested"}
    details = {"copay", "share", "waived", "admitted", "admission", "allowance", "discount", "off",
               "combine", "combined", "due", "still", "happen", "after", "before", "according", "first",
               "obtain", "frequency", "differ", "different", "listed", "usually", "needed", "much"}
    wanted -= {"due", "still", "happen", "according", "after", "before", "different", "differ"}
    subject = {word for word in wanted - details if not word.isdigit()}
    labels = [terms(f"{c.context if c.kind == 'benefit' else ''} {c.label}") - details for c in cards]
    all_terms = [terms(c.search_text) for c in cards]
    # Generic row names need their clinical section or tier to be identifiable.
    for i,c in enumerate(cards):
        if labels[i] <= {"inpatient", "outpatient", "retail", "mailorder"} or c.label.startswith("Room and board"):
            labels[i] |= terms(c.section) - {"professional", "other", "feature"}
    if not subject:
        subject = wanted
    eligible = list(range(len(cards)))
    asks_exclusion = bool(re.search(
        r"\b(?:excluded|exclusions?|does not cover|doesn't cover|will not pay|won't pay)\b|(?<!if )\bnot covered\b",
        question, re.I))
    if asks_exclusion:
        exclusion_rows = [i for i in eligible if cards[i].kind == "exclusion"]
        if exclusion_rows:
            eligible = exclusion_rows
    if re.search(r"out[- ]of[- ]network", question, re.I):
        eligible = [i for i in eligible if re.search(r"out[- ]of[- ]network", cards[i].wording, re.I)]
    # Qualifiers that distinguish clinically different rows cannot be ignored.
    modifiers = {"mental", "addiction", "autism", "maternity", "bariatric", "cosmetic"}
    eligible = [i for i in eligible if not ((labels[i] & modifiers) - subject)]
    eligible = [i for i in eligible if not (
        ("non" not in subject and re.match(r"^Non[- ]", cards[i].label, re.I)) or
        ("deductible" in subject and "drug" not in subject and "drug" in labels[i]))]
    for requested, other in (("inpatient", "outpatient"), ("outpatient", "inpatient")):
        if requested in subject and other not in subject:
            eligible = [i for i in eligible if not (other in terms(cards[i].section + " " + cards[i].label)
                        and requested not in all_terms[i])]
    # If the complete requested subject is an explicit source label, do not
    # add unrelated rows merely because an attached note mentions those words.
    # Compound questions still use the multi-row coverage path below.
    if not re.search(r"\band\b|,|\bcompare\b|\bversus\b", question, re.I):
        exact_labels = [i for i in eligible if subject <= labels[i]]
        if exact_labels:
            eligible = exact_labels
        else:
            label_overlap = {i: len(subject & labels[i]) for i in eligible}
            best_overlap = max(label_overlap.values(), default=0)
            if best_overlap:
                eligible = [i for i in eligible if label_overlap[i] == best_overlap]
    unknown = subject - set().union(*(all_terms[i] for i in eligible)) if eligible else subject
    if unknown:
        return [], {"reason": "unsupported_subject", "unmatched_terms": sorted(unknown), "corrections": corrections}
    from rank_bm25 import BM25Okapi
    bm = BM25Okapi([sorted(t) for t in all_terms])
    scores = bm.get_scores(sorted(wanted))
    anchor_words = subject & set().union(*(labels[i] for i in eligible))
    frequency = bool(re.search(r"how often|frequency", question, re.I))
    def matched(i):
        # An explicit service label beats incidental mentions in another row's note.
        return (subject & labels[i]) | ((subject - anchor_words) & all_terms[i])
    if frequency:
        frequency_rows = [i for i in eligible if re.search(r"how often|frequency", cards[i].label, re.I)]
        if frequency_rows:
            anchor_words -= set().union(*(all_terms[i] for i in frequency_rows))
    def score(i, remaining):
        hits = matched(i) & remaining
        extra = labels[i] - subject - {"care", "physician", "routine", "most", "calendar", "year", "test"}
        return (len(hits), -len(extra), cards[i].kind == "benefit", len(wanted & all_terms[i]), float(scores[i]))
    selected = []
    remaining = set(subject)
    while remaining:
        candidates = [i for i in eligible if matched(i) & remaining]
        if not candidates:
            return [], {"reason": "incomplete_question", "unmatched_terms": sorted(remaining)}
        index = max(candidates, key=lambda i: score(i, remaining))
        selected.append(index)
        remaining -= matched(index)
    # Include all explicitly named service/tier combinations, not just a single winner.
    for i in eligible:
        if not frequency and cards[i].kind == "benefit" and labels[i] and labels[i] <= subject:
            selected.append(i)
    # Preserve a requested copay alongside the frequency passage when they are separate.
    if frequency and "copay" in wanted:
        copays = [i for i in eligible if "copay" in terms(cards[i].context) and
                  re.search(r"\$", cards[i].wording)]
        if copays:
            selected.append(max(copays, key=lambda i: float(scores[i])))
    if "allowance" in wanted:
        for i in eligible:
            if "allowance" in terms(cards[i].label) and labels[i] & subject:
                selected.append(i)
    if not re.search(r"\band\b|,|\bcompare\b|\bversus\b", question, re.I):
        complete = [i for i in selected if subject <= labels[i]]
        if complete:
            smallest = min(len(labels[i] - subject) for i in complete)
            selected = [i for i in complete if len(labels[i] - subject) == smallest]
    chosen = [cards[i] for i in sorted(set(selected))]
    if len(chosen) > 1 and not re.search(r"\band\b|,|\bcompare\b|\bversus\b", question, re.I):
        subjects = [labels[i] & subject for i in set(selected)]
        if subjects and not set.intersection(*subjects):
            return [], {"reason": "ambiguous_service_combination", "choices": [c.label for c in chosen]}
    if len(chosen) > 12:
        return [], {"reason": "too_many_service_contexts", "choices": [c.label for c in chosen]}
    conflicts = defaultdict(set)
    doc_ids = defaultdict(set)
    for c in chosen:
        key = clean(c.label.lower())
        conflicts[key].add(c.wording)
        doc_ids[key].add(c.document_id)
    if any(len(v) > 1 and len(doc_ids[k]) > 1 for k,v in conflicts.items()):
        return [], {"reason": "conflicting_documents"}
    return chosen, {"catalog_passages": len(cards), "corrections": corrections,
                    "matched_labels": [c.label for c in chosen]}


def project_passage(card: Passage, question: str) -> Passage:
    """Quote only an explicitly labeled requested scope; never calculate a benefit."""
    individual = bool(re.search(r"\bindividual\b|self[- ]only", question, re.I))
    family = bool(re.search(r"\bfamily\b", question, re.I))
    inpatient = bool(re.search(r"\binpatient\b", question, re.I))
    outpatient = bool(re.search(r"\boutpatient\b", question, re.I))
    rows = []
    for row in card.rows:
        if individual != family and re.search(r"\b(?:Individual|Family)\b", " ".join(row), re.I):
            wanted, unwanted = ("Individual", "Family") if individual else ("Family", "Individual")
            if re.search(rf"\b{unwanted}\b", " ".join(row), re.I) and not re.search(rf"\b{wanted}\b", " ".join(row), re.I):
                continue
        new_row = []
        for value in row:
            if inpatient != outpatient and re.search(r"Inpatient[^:]*:.*Outpatient[^:]*:", value, re.I):
                parts = re.split(r"(?=\bOutpatient[^:]*:)", value, maxsplit=1, flags=re.I)
                value = parts[0] if inpatient else parts[-1]
            new_row.append(value)
        rows.append(new_row)
    return replace(card, rows=rows or card.rows)
