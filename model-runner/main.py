import os
import json
from fastapi import FastAPI
from pydantic import BaseModel
from transformers import pipeline
from prometheus_client import Counter, Histogram, Gauge, Info, generate_latest, CONTENT_TYPE_LATEST
from fastapi.responses import Response, JSONResponse
import time

MODEL_NAME = os.environ.get("MODEL_NAME", "distilbert-base-uncased-finetuned-sst-2-english")
TASK_TYPE  = os.environ.get("TASK_TYPE", "sentiment-analysis")

print(f"[runner] loading model={MODEL_NAME} task={TASK_TYPE}", flush=True)
classifier = pipeline(TASK_TYPE, model=MODEL_NAME)
print("[runner] model loaded", flush=True)

app = FastAPI()

PREDICTION_COUNT      = Counter("predictions_total", "Total predictions", ["label"])
PREDICTION_LATENCY    = Histogram("prediction_latency_seconds", "Prediction latency")
# Point-in-time value (not a distribution) — the confidence score of
# whichever prediction was served most recently. Paired with
# PREDICTION_LATENCY, which already tracks the full histogram, so a
# separate histogram for confidence wasn't asked for and isn't added here.
PREDICTION_CONFIDENCE = Gauge("prediction_confidence", "Confidence score of the most recent prediction")
# Info, not a per-label Gauge/Counter: this backend deploys one runner
# pod per model_name/task_type via /deploy-model (see main.py), so the
# label vocabulary here is small and fixed per deployment — but a raw
# per-label Counter already exists above (PREDICTION_COUNT). This is
# specifically "what did it say most recently", which Info's replace-on-
# set semantics (one active series, not one per label ever seen) suit
# better than a Gauge that would otherwise need explicit resets.
LAST_PREDICTION = Info("last_prediction", "Label of the most recently served prediction")

class TextIn(BaseModel):
    text: str
    labels: list[str] = ["technology", "sports", "politics", "entertainment", "business"]

@app.get("/health")
def health():
    return {"status": "ok", "model": MODEL_NAME, "task": TASK_TYPE}

@app.get("/metrics")
def metrics():
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


def _record_metrics(label, score, start):
    PREDICTION_COUNT.labels(label=label or "n/a").inc()
    PREDICTION_LATENCY.observe(time.time() - start)
    if score is not None:
        PREDICTION_CONFIDENCE.set(score)
    LAST_PREDICTION.info({"label": label or "n/a"})


def _jsonable(value):
    """Coerce common non-JSON-serializable pipeline return types (numpy
    scalars, torch tensors, ...) to plain Python values — same approach
    as custom-runner/base/main.py's helper of the same name, for the
    task types below that don't get their own hand-written response
    shape."""
    if hasattr(value, "item"):
        try:
            return value.item()
        except Exception:
            pass
    try:
        json.dumps(value)
        return value
    except TypeError:
        return str(value)


def _extract_label_score(result):
    """Best-effort — only pulls a label/score out of pipeline outputs
    shaped like the classification convention (a dict, or the first
    entry of a list of dicts, carrying "label"/"score" keys — this
    covers text-classification and image-classification's top
    prediction). Task types with no single "the answer" label
    (text-generation, summarization, translation, question-answering,
    fill-mask, token-classification's list of entities) legitimately
    have nothing to extract — metrics for those record label "n/a"
    rather than inventing one."""
    candidate = result[0] if isinstance(result, list) and len(result) >= 1 else result
    if isinstance(candidate, dict) and "label" in candidate and "score" in candidate:
        try:
            return str(candidate["label"]), float(candidate["score"])
        except (TypeError, ValueError):
            return None, None
    return None, None


@app.post("/predict")
def predict(input: TextIn):
    start = time.time()
    try:
        if TASK_TYPE == "zero-shot-classification":
            result = classifier(input.text, candidate_labels=input.labels)
            label  = result["labels"][0]
            score  = result["scores"][0]
            _record_metrics(label, score, start)
            return {
                "label": label,
                "score": round(score, 4),
                "all_labels": dict(zip(result["labels"], [round(s, 4) for s in result["scores"]]))
            }
        elif TASK_TYPE == "sentiment-analysis":
            result = classifier(input.text)[0]
            _record_metrics(result["label"], result["score"], start)
            return {"label": result["label"], "score": round(result["score"], 4)}
        else:
            # text-classification, token-classification, text-generation,
            # summarization, translation, question-answering, fill-mask,
            # image-classification, and anything else `transformers.
            # pipeline()` accepts as a task string — no per-task response
            # shape here, just the pipeline's own output, made JSON-safe.
            result = classifier(input.text)
            label, score = _extract_label_score(result)
            _record_metrics(label, score, start)
            return {"result": _jsonable(result)}
    except Exception as e:
        return JSONResponse(status_code=400, content={"error": str(e)})
