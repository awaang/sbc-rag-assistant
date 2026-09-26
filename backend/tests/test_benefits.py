from app.benefits import extract_candidates
from app.ingestion import parse_pdf
from pathlib import Path


def test_candidate_values_keep_exact_source_and_dimensions_for_review():
    candidates = extract_candidates([{
        "page_number": 3,
        "section_heading": "What You Will Pay",
        "text": "In-network individual deductible: $1,200",
    }])

    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate.category == "deductible"
    assert candidate.value_text == "In-network individual deductible: $1,200"
    assert candidate.page_number == 3
    assert candidate.section == "What You Will Pay"
    assert candidate.dimensions == {"network": "In-network", "individual": "individual"}
    assert candidate.status == "pending_review"


def test_distinct_values_on_a_source_row_are_marked_ambiguous():
    candidates = extract_candidates([{
        "page_number": 1,
        "text": "Emergency room: $250 copay and 20% coinsurance",
    }])

    assert len(candidates) == 1
    assert candidates[0].category == "er_cost_sharing"
    assert candidates[0].status == "ambiguous"
    assert candidates[0].dimensions["coinsurance"] == "coinsurance"


def test_same_repeated_value_does_not_create_false_ambiguity():
    candidates = extract_candidates([{
        "page_number": 1,
        "text": "$20 copay: $20 copay",
    }])

    assert len(candidates) == 1
    assert candidates[0].status == "pending_review"


def test_aetna_received_pdf_emits_individual_and_family_oop_candidates():
    repository_root = Path(__file__).resolve().parents[2]
    source_pdf = repository_root / "data/source-documents/received/Aetna HMO Plan Summary 01.01.2017.pdf"
    pages = parse_pdf(source_pdf.read_bytes())

    candidates = extract_candidates(pages)
    oop = [candidate for candidate in candidates if candidate.category == "out_of_pocket_maximum"]

    assert len(oop) == 2
    assert {candidate.value_text for candidate in oop} == {
        "Out-of-Pocket Maximum: $2,500 Individual (per calendar year)",
        "Out-of-Pocket Maximum: $5,000 Family (per calendar year)",
    }
    assert all(candidate.dimensions["network"] == "IN-NETWORK" for candidate in oop)
    assert all(candidate.dimensions["period"] == "calendar year" for candidate in oop)
    assert all(candidate.status == "pending_review" for candidate in oop)

    emergency_room = next(candidate for candidate in candidates
                          if candidate.category == "er_cost_sharing"
                          and candidate.value_text.startswith("Emergency Room:"))
    assert emergency_room.section == "EMERGENCY MEDICAL CARE"
    assert emergency_room.dimensions["network"] == "IN-NETWORK"


def test_table_continuations_and_network_columns_keep_distinct_contexts():
    candidates = extract_candidates([{
        "page_number": 1,
        "section_heading": "PLAN FEATURES",
        "text": "",
        "tables": [{
            "headers": ["", "PLAN FEATURES", "", "", "IN-NETWORK", "", "OUT-OF-NETWORK"],
            "header_row_index": 0,
            "rows": [
                ["", "Deductible (per calendar year)", "", "", "$300 Individual", "", "$600 Individual"],
                ["", "", "", "", "$600 Family", "", "$1,200 Family"],
            ],
        }],
    }])

    deductible = [candidate for candidate in candidates if candidate.category == "deductible"]
    assert {(candidate.value_text, candidate.dimensions["network"],
             candidate.dimensions.get("family", candidate.dimensions.get("individual")))
            for candidate in deductible} == {
        ("Deductible (per calendar year): $300 Individual (per calendar year)", "IN-NETWORK", "Individual"),
        ("Deductible (per calendar year): $600 Individual (per calendar year)", "OUT-OF-NETWORK", "Individual"),
        ("Deductible (per calendar year): $600 Family (per calendar year)", "IN-NETWORK", "Family"),
        ("Deductible (per calendar year): $1,200 Family (per calendar year)", "OUT-OF-NETWORK", "Family"),
    }


def test_multiple_scopes_in_one_parsed_cell_become_separate_records():
    candidates = extract_candidates([{
        "page_number": 1,
        "text": "",
        "tables": [{
            "headers": ["Benefits", "Inside Network"],
            "header_row_index": 0,
            "rows": [["Out-of-pocket limit", "Individual out-of-pocket limit: $2,000 Family out-of-pocket limit: $4,000"]],
        }],
    }])

    oop = [candidate for candidate in candidates if candidate.category == "out_of_pocket_maximum"]
    assert {candidate.value_text for candidate in oop} == {
        "Out-of-pocket limit: $2,000 Individual",
        "Out-of-pocket limit: $4,000 Family",
    }
    assert {candidate.dimensions["individual"] for candidate in oop if "individual" in candidate.dimensions} == {"Individual"}
    assert {candidate.dimensions["family"] for candidate in oop if "family" in candidate.dimensions} == {"Family"}


def test_kaiser_family_each_member_header_is_preserved_separately():
    repository_root = Path(__file__).resolve().parents[2]
    source_pdf = repository_root / "data/source-documents/received/Kaiser HMO Plan Summary 2017.pdf"
    candidates = extract_candidates(parse_pdf(source_pdf.read_bytes()))
    oop = [candidate for candidate in candidates if candidate.category == "out_of_pocket_maximum"]

    assert len(oop) == 3
    per_member = next(candidate for candidate in oop if "family_context" in candidate.dimensions)
    assert per_member.value_text == "Plan Out-of-Pocket Maximum: $1,500 Individual"
    assert per_member.dimensions["family_context"].startswith("Family Coverage Each Member")
    assert per_member.status == "pending_review"


def test_kaiser_candidates_use_benefit_sections_instead_of_column_headers():
    repository_root = Path(__file__).resolve().parents[2]
    source_pdf = repository_root / "data/source-documents/received/Kaiser HMO Plan Summary 2017.pdf"
    candidates = extract_candidates(parse_pdf(source_pdf.read_bytes()))

    deductible = [item for item in candidates if item.category == "deductible"
                  and item.value_text.startswith("Plan Deductible")]
    emergency = [item for item in candidates if item.category == "er_cost_sharing"]
    assert len(deductible) == 3
    assert {item.section for item in deductible} == {"Out-of-Pocket Maximum(s) and Deductible(s)"}
    assert len(emergency) == 1
    assert emergency[0].section == "Emergency Health Coverage You Pay"


def _table_page(page_number, headers, rows, row_sections=None, section_heading=None):
    return {"page_number": page_number, "text": "", "section_heading": section_heading,
            "tables": [{"headers": headers, "header_row_index": 0 if headers else None,
                        "rows": ([headers] if headers else []) + rows, "row_sections": row_sections or []}]}


def test_no_annual_deductible_is_a_none_value():
    candidates = extract_candidates([_table_page(1, ["Benefits", "Inside Network"],
                                                 [["Plan deductible", "No annual deductible"]])])
    assert [(c.category, c.value_text) for c in candidates] == [("deductible", "Plan deductible: No annual deductible")]


def test_emergency_services_row_is_er_cost_sharing_not_a_copay():
    candidates = extract_candidates([_table_page(1, ["Benefits", "", "Inside Network"],
                                                 [["Emergency services (copay waived if admitted)", "", "$100 copay"]])])
    assert {c.category for c in candidates} == {"er_cost_sharing"}


def test_flat_amount_per_primary_care_or_specialist_visit_is_a_copay():
    candidates = extract_candidates([{"page_number": 1, "text": (
        "Most Primary Care Visits ........ $30 per visit\n"
        "Most Physician Specialist Visits ........ $30 per visit")}])
    assert [c.category for c in candidates] == ["copay", "copay"]
    assert all(c.status == "pending_review" for c in candidates)


def test_out_of_network_reimbursement_amounts_are_not_copays():
    candidates = extract_candidates([_table_page(1, ["", "In-Network", "Out-Of-Network"],
                                                 [["Eye exams", "$10 copay", "Amount over: $50.00"]])])
    assert [(c.value_text.rsplit(": ", 1)[1], c.dimensions.get("network")) for c in candidates] == [("$10", "IN-NETWORK")]


def test_table_continued_on_next_page_keeps_network_headers_and_section():
    headers = ["", "PHYSICIAN SERVICES", "IN-NETWORK", "OUT-OF-NETWORK"]
    candidates = extract_candidates([
        _table_page(1, headers, [["", "Primary Care Visits", "$20 copay", "40%"]],
                    row_sections=["PHYSICIAN SERVICES", "PHYSICIAN SERVICES"]),
        _table_page(2, [], [["", "Specialist Office Visits", "$30 copay", "40%"]],
                    row_sections=["PLAN DESIGN & BENEFITS"]),
    ])
    specialist = [c for c in candidates if c.page_number == 2]
    assert {(c.value_text, c.dimensions.get("network"), c.section) for c in specialist} == {
        ("Specialist Office Visits: $30", "IN-NETWORK", "PHYSICIAN SERVICES"),
        ("Specialist Office Visits: 40%", "OUT-OF-NETWORK", "PHYSICIAN SERVICES"),
    }
