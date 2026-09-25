from app.benefits import extract_candidates


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
