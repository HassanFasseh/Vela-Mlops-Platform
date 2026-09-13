"""
Explains a single prediction result in plain language - "why this output,
what in the input likely drove it" - for a member looking at a result
they already have (from /api/v1/predict). This module does NOT call the
model itself; it takes an already-obtained result and explains it, so
there's no duplicate model-service call and no new prediction path.

Reuses services/llm_provider.py's call_llm() exactly - same admin-
configured provider (external or on-prem), same fail-soft contract, same
on-prem-never-falls-back-externally guarantee drift explanation already
has. This module only builds a prompt and never talks to an LLM vendor
directly.

Fail-soft, deliberately narrower than call_llm()'s own contract: call_llm()
bakes its failure reason into the returned string (vendor error text and
all - fine for drift's own UI, which shows it as-is). This module strips
that back out via UNAVAILABLE_PREFIX and always returns the same calm
"explanation unavailable" message on any failure - no provider configured,
misconfigured, network error, bad key, on-prem unreachable - so a member
never sees a vendor error string.
"""

import json

from backend.app.services.llm_provider import call_llm, UNAVAILABLE_PREFIX

_MAX_INPUT_CHARS = 1000
_MAX_OUTPUT_CHARS = 1000

FALLBACK_MESSAGE = "Explanation unavailable right now."


def _truncate(value, limit: int) -> str:
    s = str(value)
    return s if len(s) <= limit else s[:limit] + "…"


def _describe_input(input_type: str, text: str | None, data: dict | None, labels: list | None) -> str:
    if input_type == "file":
        # Raw base64 never goes into the prompt - there's nothing useful
        # an LLM can say about undescribed binary content, and pasting it
        # in would defeat the point of an on-prem/regulated setup for no
        # benefit.
        return "an uploaded file (image or audio) - content omitted from this explanation"

    if input_type == "json" and data is not None:
        try:
            rendered = json.dumps(data)
        except Exception:
            rendered = str(data)
        return "structured input: " + _truncate(rendered, _MAX_INPUT_CHARS)

    if text:
        rendered = 'text input: "' + _truncate(text, _MAX_INPUT_CHARS) + '"'
        if labels:
            rendered += "\ncandidate labels considered: " + ", ".join(str(l) for l in labels)
        return rendered

    return "no input details available"


def _describe_result(result) -> str:
    if not isinstance(result, dict):
        return "output: " + _truncate(result, _MAX_OUTPUT_CHARS)

    # Same three shapes predictor.js's renderResult() already branches on.
    all_labels = result.get("all_labels")
    if all_labels:
        ranked = sorted(all_labels.items(), key=lambda kv: kv[1], reverse=True)[:5]
        lines = [f"- {label}: {round(score * 100, 1)}%" for label, score in ranked]
        return "ranked label scores:\n" + "\n".join(lines)

    if result.get("label") is not None:
        line = f"predicted label: {result['label']}"
        score = result.get("score")
        if score is not None:
            line += f" (confidence {round(score * 100, 1)}%)"
        return line

    if "result" in result:
        return "raw model output: " + _truncate(result["result"], _MAX_OUTPUT_CHARS)

    return "output: " + _truncate(result, _MAX_OUTPUT_CHARS)


PROMPT_TEMPLATE = """You are explaining a single prediction from a deployed machine learning model to the person who ran it. Be plain-language, concise (2-4 sentences), and honest about what you can and can't know.

Model: {model_name} ({task_type})

Input given to the model:
{input_desc}

Output the model produced:
{output_desc}

Explain in plain language what this result means and which parts of the input most plausibly drove it. Rules:
- Never claim you have access to the model's actual internal weights or reasoning - you're inferring plausible drivers from the input/output pair alone, not reporting ground truth.
- Point to SPECIFIC words, phrases, or fields in the input where possible, not vague generalities.
- If the output doesn't obviously connect to anything in the input, say so honestly rather than inventing a connection.
- Do not just repeat the raw score/label back verbatim without adding plain-language context."""


def build_prompt(model_name: str | None, task_type: str | None, input_type: str,
                  text: str | None, data: dict | None, labels: list | None, result) -> str:
    return PROMPT_TEMPLATE.format(
        model_name=model_name or "this model",
        task_type=task_type or "unknown task",
        input_desc=_describe_input(input_type, text, data, labels),
        output_desc=_describe_result(result),
    )


def explain_prediction(model_name: str | None, task_type: str | None, input_type: str,
                        text: str | None, data: dict | None, labels: list | None, result) -> str:
    """Always returns display text. Never raises, never leaks a vendor
    error string - any failure (no provider, misconfigured, network,
    bad key, on-prem unreachable) collapses to FALLBACK_MESSAGE."""
    try:
        prompt = build_prompt(model_name, task_type, input_type, text, data, labels, result)
    except Exception:
        return FALLBACK_MESSAGE

    text_out = call_llm(prompt)
    if not text_out or text_out.startswith(UNAVAILABLE_PREFIX):
        return FALLBACK_MESSAGE
    return text_out
