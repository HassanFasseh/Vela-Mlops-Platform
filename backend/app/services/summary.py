import os
import json
import requests as req
from groq import Groq
from datetime import datetime

GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
MODEL_SERVICE_URL = os.environ.get("MODEL_SERVICE_URL", "http://model-service.default.svc.cluster.local")

def get_drift_details() -> dict:
    try:
        r = req.get(f"{MODEL_SERVICE_URL}/drift-details", timeout=3)
        return r.json()
    except Exception:
        return {"drift_share": 0.0, "columns": [], "computed_at": None}

def build_prompt(events: list) -> str:
    if not events:
        return ""
    deploy_events = [e for e in events if e["type"] == "deploy"]
    drift_events  = [e for e in events if e["type"] == "drift"]
    latency_events = [e for e in events if e["type"] == "latency_p95"]

    def fmt(ts):
        return datetime.utcfromtimestamp(ts).strftime("%H:%M:%S UTC")

    lines = []
    if deploy_events:
        lines.append(f"- {len(deploy_events)} deploy event(s): latest at {fmt(deploy_events[-1]['timestamp'])}")
    if drift_events:
        scores = [e['detail'] for e in drift_events[-3:]]
        lines.append(f"- Drift score (recent samples): {', '.join(scores)}")

    # Population-level column breakdown
    drift_detail = get_drift_details()
    if drift_detail.get("columns"):
        drifted = [c for c in drift_detail["columns"] if c["drifted"]]
        stable  = [c for c in drift_detail["columns"] if not c["drifted"]]
        if drifted:
            col_str = ", ".join([f"{c['column']} (p={c['p_value']:.3f}, method={c['method']})" for c in drifted])
            lines.append(f"- Drifted columns: {col_str}")
        if stable:
            lines.append(f"- Stable columns: {', '.join([c['column'] for c in stable])}")

    if latency_events:
        recent = latency_events[-5:]
        lines.append(f"- p95 latency (recent): {', '.join(e['detail'] for e in recent)}")

    return "\n".join(lines) if lines else ""

PROMPT_TEMPLATE = """You are an MLOps observability assistant. Given a structured summary of events from a production ML deployment, explain in 2-3 plain-language sentences what is happening and what the most likely correlated factors are.

Rules:
- Never claim causation. Only surface the most likely correlated factor.
- If drift is above 0.3, flag it as noteworthy.
- Name specific drifted columns when available (e.g. "the confidence score distribution and label distribution have both shifted").
- If no latency data is available, say so.
- Keep the response concise and factual.

Event summary:
{summary}

Write a plain-language explanation without claiming proven causation."""

def try_groq(prompt: str) -> str:
    client = Groq(api_key=GROQ_API_KEY)
    response = client.chat.completions.create(
        messages=[
            {"role": "system", "content": "You are a concise, honest MLOps observability assistant."},
            {"role": "user", "content": prompt}
        ],
        model="openai/gpt-oss-20b",
        max_tokens=400,
        temperature=0.3,
    )
    return response.choices[0].message.content.strip()

def try_gemini(prompt: str) -> str:
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={GEMINI_API_KEY}"
    body = {"contents": [{"parts": [{"text": prompt}]}]}
    r = req.post(url, json=body, timeout=15)
    r.raise_for_status()
    return r.json()["candidates"][0]["content"]["parts"][0]["text"].strip()

def generate_summary(events: list) -> str:
    if not events:
        return "No events in the current time window to summarize."

    summary_lines = build_prompt(events)
    if not summary_lines:
        return "Insufficient signal to generate a summary."

    prompt = PROMPT_TEMPLATE.format(summary=summary_lines)

    if GROQ_API_KEY:
        try:
            return try_groq(prompt)
        except Exception as e:
            if "429" in str(e) or "rate_limit" in str(e).lower():
                pass  # fall through to Gemini
            else:
                pass  # fall through to Gemini on any error

    if GEMINI_API_KEY:
        try:
            return try_gemini(prompt)
        except Exception as e:
            return f"LLM summary unavailable (both providers failed): {str(e)[:100]}"

    return "LLM summary unavailable: no API keys configured."
