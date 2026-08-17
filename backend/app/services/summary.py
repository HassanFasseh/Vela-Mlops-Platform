import os
import json
from groq import Groq
from datetime import datetime

GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")

def generate_summary(events: list) -> str:
    if not GROQ_API_KEY:
        return "Summary unavailable: GROQ_API_KEY not set."

    if not events:
        return "No events in the current time window to summarize."

    # Build a concise, structured representation — not the full JSON blob
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
    if latency_events:
        recent = latency_events[-5:]
        lines.append(f"- p95 latency (recent): {', '.join(e['detail'] for e in recent)}")

    if not lines:
        return "Insufficient signal to generate a summary."

    prompt = f"""You are an MLOps observability assistant. You are given a structured summary of events from a production model deployment system. Your job is to explain in 2-3 plain-language sentences what is happening and what the most likely correlated factors are.

Rules:
- Never claim causation. Only surface the most likely correlated factor.
- If drift is above 0.3, flag it as noteworthy.
- If no latency data is available, say so and focus on what is available.
- Keep the response concise and factual.

Event summary:
{chr(10).join(lines)}

Write a plain-language explanation of what this data suggests, without claiming proven causation."""

    client = Groq(api_key=GROQ_API_KEY)
    response = client.chat.completions.create(
        messages=[
            {"role": "system", "content": "You are a concise, honest MLOps observability assistant."},
            {"role": "user", "content": prompt}
        ],
        model="openai/gpt-oss-20b",
        max_tokens=200,
        temperature=0.3,
    )
    return response.choices[0].message.content.strip()
