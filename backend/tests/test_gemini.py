import json

import httpx
import pytest

from app import gemini


def _result(status="answered", answer="Deductible source wording: Plan A: $1,500 per person.", facts=True,
            kind="source_passages"):
    result = {"status": status, "answer": answer, "citations": [], "matched_plans": ["Plan A"],
              "context_plan_ids": [1], "debug": {"latency_ms": 5.0}}
    if facts:
        result["_gemini_facts"] = {"kind": kind, "category": "deductible", "comparison": "",
                                   "facts": [{"plan": "Plan A", "value": "$1,500 per person"}]}
    return result


@pytest.fixture
def gemini_reply(monkeypatch):
    monkeypatch.setenv("GEMINI_ENABLED", "true")
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    calls = []

    def install(answer=None, status_code=200):
        def handler(request):
            calls.append(json.loads(request.content))
            body = {"candidates": [{"content": {"parts": [{"text": json.dumps({"answer": answer})}]}}],
                    "usageMetadata": {"promptTokenCount": 10, "candidatesTokenCount": 5, "totalTokenCount": 15}}
            return httpx.Response(status_code, json=body)

        real_client = httpx.Client
        monkeypatch.setattr(gemini.httpx, "Client",
                            lambda **kwargs: real_client(transport=httpx.MockTransport(handler), **kwargs))
        return calls

    return install


def test_uses_gemini_answer_when_values_are_preserved(gemini_reply):
    gemini_reply("Plan A has a deductible of $1,500 per person.")
    result = gemini.phrase_answer(_result())
    assert result["answer"].startswith("Plan A has a deductible of $1,500")
    assert result["debug"]["phrasing"] == "gemini"
    assert result["debug"]["gemini_tokens"]["total"] == 15


@pytest.mark.parametrize("status", ["insufficient_evidence", "clarification_needed"])
def test_abstention_and_clarification_skip_gemini(gemini_reply, status):
    calls = gemini_reply("I couldn't find that value in the available plan documents.")
    result = gemini.phrase_answer(_result(status, "I can’t establish the requested value.", facts=False))
    assert result["status"] == status
    assert result["answer"] == "I can’t establish the requested value."
    assert result["debug"]["gemini_status"] == "skipped_no_answer"
    assert calls == []


def test_structured_answer_skips_gemini(gemini_reply):
    calls = gemini_reply("Plan A has a deductible of $1,500 per person.")
    result = gemini.phrase_answer(_result(kind="numeric"))
    assert result["answer"] == _result()["answer"]
    assert result["debug"]["gemini_status"] == "skipped_structured_answer"
    assert result["debug"]["phrasing"] == "deterministic"
    assert calls == []


def test_invented_number_falls_back_to_deterministic_answer(gemini_reply):
    gemini_reply("Plan A has a deductible of $1,500 per person and $3,000 per family.")
    original = _result()["answer"]
    result = gemini.phrase_answer(_result())
    assert result["answer"] == original
    assert result["debug"]["gemini_status"] == "failed_evidence_check"


def test_missing_checked_value_falls_back(gemini_reply):
    gemini_reply("Plan A has a deductible.")
    result = gemini.phrase_answer(_result())
    assert result["debug"]["phrasing"] == "deterministic"


def test_omitted_admission_exception_falls_back(gemini_reply):
    gemini_reply("The emergency room copay is $100.")
    result = _result(answer="The emergency room copay is $100; waived if admitted.")
    result["_gemini_facts"] = {
        "kind": "coverage", "facts": [{"plan": "Plan A", "wording": "$100 copay; waived if admitted"}],
        "required_terms": ["waived", "admitted"],
    }
    phrased = gemini.phrase_answer(result)
    assert phrased["answer"] == "The emergency room copay is $100; waived if admitted."
    assert phrased["debug"]["gemini_status"] == "failed_evidence_check"


def test_api_error_falls_back(gemini_reply):
    gemini_reply(status_code=500)
    result = gemini.phrase_answer(_result())
    assert result["debug"]["gemini_status"] == "http_error"
    assert result["debug"]["gemini_http_status"] == 500
    assert result["answer"] == _result()["answer"]


def test_disabled_leaves_answer_unchanged(monkeypatch):
    monkeypatch.setenv("GEMINI_ENABLED", "false")
    result = gemini.phrase_answer(_result())
    assert "_gemini_facts" not in result
    assert "phrasing" not in result["debug"]
