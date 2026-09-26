"""Gemini-written responses over server-checked evidence."""

from __future__ import annotations

import json
import os
import re
import time
from typing import Any

import httpx


MODEL = "gemini-3.1-flash-lite"
NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?")
INSTRUCTIONS = (
    "You write the reply for a health-benefits assistant. The server has already checked the evidence "
    "and decided the reply type in `status`. Rewrite `draft_answer` as a clear, friendly reply of at most "
    "four sentences.\n"
    "Rules:\n"
    "- Use only information in the supplied JSON. Never add benefit facts, amounts, percentages, plans, "
    "or advice about which plan to choose.\n"
    "- For status `answered`, state every value from `facts` exactly as written, name its plan, and keep "
    "any comparison and the provisional-document caveat.\n"
    "- For status `clarification_needed`, ask the user for the missing detail described in the draft.\n"
    "- For status `insufficient_evidence`, say the answer can't be established from the available "
    "documents and give the draft's reason. Do not guess a value.\n"
    "- Do not include citations, page numbers, markdown, or numbered lists; the app shows citations separately."
)


def _numbers(text: str) -> set[str]:
    return {match.replace(",", "") for match in NUMBER.findall(text)}


def _evidence(result: dict[str, Any], facts: dict[str, Any] | None) -> dict[str, Any]:
    evidence: dict[str, Any] = {
        "status": result["status"],
        "draft_answer": result["answer"],
        "matched_plans": result.get("matched_plans", []),
    }
    if facts:
        evidence.update({key: facts[key] for key in ("category", "comparison", "facts", "caveat") if facts.get(key)})
    return evidence


def _check(answer: str, evidence: dict[str, Any]) -> bool:
    """Reject replies with numbers absent from the evidence or missing a checked value."""
    if not answer:
        return False
    if not _numbers(answer) <= _numbers(json.dumps(evidence, ensure_ascii=False)):
        return False
    if evidence["status"] == "answered":
        stated = _numbers(answer)
        for fact in evidence.get("facts", []):
            if not _numbers(str(fact.get("value") or fact.get("wording") or "")) <= stated:
                return False
    return True


def phrase_answer(result: dict[str, Any]) -> dict[str, Any]:
    """Have Gemini write the reply; the server keeps status, citations, and the evidence check."""
    facts = result.pop("_gemini_facts", None)
    if os.getenv("GEMINI_ENABLED", "false").lower() != "true":
        return result

    debug = result["debug"]
    debug["phrasing"] = "deterministic"
    key = os.getenv("GEMINI_API_KEY", "").strip()
    if not key:
        debug["gemini_status"] = "unconfigured"
        return result

    model = os.getenv("GEMINI_MODEL", MODEL).strip()
    if not model or not all(character.isalnum() or character in "-_." for character in model):
        debug["gemini_status"] = "invalid_model"
        return result

    evidence = _evidence(result, facts)
    started = time.perf_counter()
    try:
        payload = {
            "systemInstruction": {"parts": [{"text": INSTRUCTIONS}]},
            "contents": [{"role": "user", "parts": [{"text": json.dumps(evidence, ensure_ascii=False)}]}],
            "generationConfig": {
                "temperature": 0.2,
                "responseMimeType": "application/json",
                "responseSchema": {
                    "type": "OBJECT",
                    "properties": {"answer": {"type": "STRING"}},
                    "required": ["answer"],
                },
                "maxOutputTokens": 1024,
            },
        }
        with httpx.Client(timeout=10.0) as client:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
            for attempt in range(3):
                response = client.post(url, headers={"x-goog-api-key": key}, json=payload)
                if response.status_code not in {429, 503} or attempt == 2:
                    break
                # A short exponential backoff for transient provider overload/quota responses.
                time.sleep(0.5 * (2 ** attempt))
            response.raise_for_status()
        body = response.json()
        usage = body.get("usageMetadata") or {}
        debug["gemini_model"] = model
        debug["gemini_tokens"] = {
            "input": usage.get("promptTokenCount", 0),
            "output": usage.get("candidatesTokenCount", 0),
            "total": usage.get("totalTokenCount", 0),
        }
        parts = body["candidates"][0]["content"]["parts"]
        answer = str(json.loads("".join(part.get("text", "") for part in parts))["answer"]).strip()
        if not _check(answer, evidence):
            debug["gemini_status"] = "failed_evidence_check"
            return result
        result["answer"] = answer
        debug["phrasing"] = "gemini"
        debug["gemini_status"] = "ok"
    except httpx.HTTPStatusError as exc:
        debug["gemini_status"] = "http_error"
        debug["gemini_http_status"] = exc.response.status_code
    except httpx.TimeoutException:
        debug["gemini_status"] = "timeout"
    except httpx.HTTPError:
        debug["gemini_status"] = "network_error"
    except (AttributeError, KeyError, IndexError, TypeError, ValueError):
        debug["gemini_status"] = "invalid_response"
    finally:
        debug["gemini_latency_ms"] = round((time.perf_counter() - started) * 1000, 1)
        debug["latency_ms"] = round(debug["latency_ms"] + debug["gemini_latency_ms"], 1)
    return result
