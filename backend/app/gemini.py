"""Optional Gemini selection of safe phrasing templates for checked evidence."""

from __future__ import annotations

import json
import os
import time
from typing import Any

import httpx


MODEL = "gemini-3.1-flash-lite"
TEMPLATES = {
    "numeric": {
        "benefit_sentence": lambda category, row: f"The {category} for {row['plan']} is listed as {row['value']}.",
        "document_sentence": lambda category, row: f"For {row['plan']}, the cited document lists the {category} as {row['value']}.",
    },
    "coverage": {
        "source_says": lambda _category, row: f"{row['plan']}: “{row['wording']}”.",
        "document_says": lambda _category, row: f"The cited document for {row['plan']} says: “{row['wording']}”.",
        "plan_wording": lambda _category, row: f"For {row['plan']}, the source wording is: “{row['wording']}”.",
    },
}


def phrase_answer(result: dict[str, Any]) -> dict[str, Any]:
    """Let Gemini select a style; the server fills every factual placeholder."""
    facts = result.pop("_gemini_facts", None)
    if (result["status"] != "answered" or not facts
            or os.getenv("GEMINI_ENABLED", "false").lower() != "true"):
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

    started = time.perf_counter()
    try:
        templates = TEMPLATES.get(facts.get("kind"))
        if not templates:
            debug["gemini_status"] = "unsupported_answer_type"
            return result
        # Gemini picks only a template ID. Server-owned strings fill all factual slots.
        payload = {
            "contents": [{"role": "user", "parts": [{"text": (
                "Choose the clearest phrasing template for this already-supported answer. "
                "Return only a template ID from the supplied list. Do not generate or edit facts. "
                f"Template IDs: {', '.join(templates)}. "
                f"Supported answer: {result['answer']}"
            )}]}],
            "generationConfig": {
                "responseMimeType": "application/json",
                "responseSchema": {
                    "type": "OBJECT",
                    "properties": {"template_id": {"type": "STRING", "enum": list(templates)}},
                    "required": ["template_id"],
                },
                "maxOutputTokens": 512,
            },
        }
        with httpx.Client(timeout=8.0) as client:
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
        debug["gemini_tokens"] = {
            "input": usage.get("promptTokenCount", 0),
            "output": usage.get("candidatesTokenCount", 0),
            "total": usage.get("totalTokenCount", 0),
        }
        parts = body["candidates"][0]["content"]["parts"]
        template_id = json.loads("".join(part.get("text", "") for part in parts))["template_id"]
        if template_id not in templates:
            debug["gemini_status"] = "invalid_output"
            return result
        category = facts.get("category", "")
        sentences = [templates[template_id](category, row) for row in facts["facts"]]
        answer_parts = [facts.get("comparison", ""), " ".join(sentences), facts["caveat"]]
        result["answer"] = " ".join(part for part in answer_parts if part)
        debug["phrasing"] = "gemini"
        debug["gemini_model"] = model
    except httpx.HTTPStatusError as exc:
        debug["gemini_status"] = "http_error"
        debug["gemini_http_status"] = exc.response.status_code
    except httpx.TimeoutException:
        debug["gemini_status"] = "timeout"
    except httpx.HTTPError:
        debug["gemini_status"] = "network_error"
    except (AttributeError, KeyError, IndexError, TypeError, ValueError):
        debug["gemini_status"] = "unavailable"
    finally:
        debug["gemini_latency_ms"] = round((time.perf_counter() - started) * 1000, 1)
        debug["latency_ms"] = round(debug["latency_ms"] + debug["gemini_latency_ms"], 1)
    return result
