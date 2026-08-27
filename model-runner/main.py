import base64
import io
import os
import json
import tempfile
from fastapi import FastAPI
from pydantic import BaseModel
from transformers import pipeline
from PIL import Image
from prometheus_client import Counter, Histogram, Gauge, Info, generate_latest, CONTENT_TYPE_LATEST
from fastapi.responses import Response, JSONResponse
import time

MODEL_NAME = os.environ.get("MODEL_NAME", "distilbert-base-uncased-finetuned-sst-2-english")
TASK_TYPE  = os.environ.get("TASK_TYPE", "sentiment-analysis")

IMAGE_TASKS = {"image-classification", "object-detection"}
AUDIO_TASKS = {"automatic-speech-recognition", "audio-classification"}

# Mirrors the Deployment.input_type convention used everywhere else in
# the platform (backend/app/db/models.py, custom-runner/base/main.py) —
# text, json, or file. "file" covers both images and audio; which of the
# two a given file is comes from TASK_TYPE, not a separate input_type
# value. Falls back to inferring from TASK_TYPE when INPUT_TYPE isn't
# set explicitly (e.g. model-deploy.yml's manifest not passing it), so
# an image/audio TASK_TYPE doesn't silently default to "text" and get
# handed an empty string on every request — that's what actually broke
# chest-xray: the pod ran with TASK_TYPE=image-classification but no
# INPUT_TYPE env var at all, so it defaulted to "text" and never took
# the file-decoding path below regardless of what that path did.
_default_input_type = "file" if TASK_TYPE in IMAGE_TASKS | AUDIO_TASKS else "text"
INPUT_TYPE = os.environ.get("INPUT_TYPE") or _default_input_type

print(f"[runner] loading model={MODEL_NAME} task={TASK_TYPE} input_type={INPUT_TYPE}", flush=True)
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

class PredictIn(BaseModel):
    # Which of these is actually required depends on INPUT_TYPE — see
    # the /predict handler. All optional at the schema level (same
    # approach as backend/app/main.py's PredictRequest) so one model
    # covers text/file/json deployments instead of three.
    text: str | None = None
    file: str | None = None   # base64-encoded (images, audio)
    data: dict | None = None  # e.g. {"question": ..., "context": ...}
    labels: list[str] = ["technology", "sports", "politics", "entertainment", "business"]

@app.get("/health")
def health():
    return {"status": "ok", "model": MODEL_NAME, "task": TASK_TYPE, "input_type": INPUT_TYPE}

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


def normalize_output(result):
    """Coerce whatever a transformers pipeline returned into one of a
    handful of predictable shapes, so callers (the prediction tester UI,
    API consumers) don't need to know each task type's native output
    format:
      - a list of {label, score, ...} dicts (image-classification,
        audio-classification, object-detection, ...) -> top pick plus
        the full ranking, in the same {label, score, all_labels: {...}}
        shape the zero-shot-classification branch below already uses
      - a single {label, score} dict (sentiment-analysis-shaped) ->
        returned as-is (just made JSON-safe)
      - a bare string -> {"result": string}
      - anything else (question-answering, summarization, translation,
        text-generation, fill-mask, token-classification, zero-shot's
        own {"sequence","labels","scores"} shape if it ever reaches
        here, ...) -> {"result": <raw, made JSON-safe>}
    """
    if isinstance(result, list) and result and all(
        isinstance(item, dict) and "label" in item and "score" in item for item in result
    ):
        all_labels = {}
        for item in result:
            try:
                all_labels[str(item["label"])] = round(float(item["score"]), 4)
            except (TypeError, ValueError):
                all_labels[str(item["label"])] = _jsonable(item["score"])
        top_label, top_score = next(iter(all_labels.items()))
        return {"label": top_label, "score": top_score, "all_labels": all_labels}

    if isinstance(result, dict) and "label" in result and "score" in result:
        try:
            return {"label": str(result["label"]), "score": round(float(result["score"]), 4)}
        except (TypeError, ValueError):
            return {"label": result["label"], "score": _jsonable(result["score"])}

    if isinstance(result, str):
        return {"result": result}

    return {"result": _jsonable(result)}


@app.post("/predict")
def predict(input: PredictIn):
    start = time.time()
    tmp_path = None
    try:
        if INPUT_TYPE == "file":
            if not input.file:
                raise ValueError("Missing 'file' field (base64-encoded)")
            file_bytes = base64.b64decode(input.file)
            if TASK_TYPE in AUDIO_TASKS:
                # transformers' ASR/audio-classification pipelines take a
                # file path (or raw array) — write the decoded bytes out
                # since we only have them in memory.
                with tempfile.NamedTemporaryFile(delete=False) as tmp:
                    tmp.write(file_bytes)
                    tmp_path = tmp.name
                result = classifier(tmp_path)
            else:
                # image-classification, object-detection, and any other
                # TASK_TYPE this deployment was given INPUT_TYPE=file
                # for — every current image pipeline in transformers
                # takes a PIL.Image. Force RGB: grayscale (chest X-rays
                # and other medical imagery are commonly single-channel),
                # RGBA, and palette-mode images all fail model forward
                # passes built around 3-channel input otherwise.
                img = Image.open(io.BytesIO(file_bytes))
                img = img.convert("RGB")
                result = classifier(img)
        elif INPUT_TYPE == "json":
            if input.data is None:
                raise ValueError("Missing 'data' field")
            if TASK_TYPE == "question-answering":
                result = classifier(question=input.data.get("question"), context=input.data.get("context"))
            else:
                result = classifier(str(input.data))
        else:
            # text (default)
            if TASK_TYPE == "zero-shot-classification":
                result = classifier(input.text or "", candidate_labels=input.labels)
                label = result["labels"][0]
                score = result["scores"][0]
                _record_metrics(label, score, start)
                return {
                    "label": label,
                    "score": round(score, 4),
                    "all_labels": dict(zip(result["labels"], [round(s, 4) for s in result["scores"]]))
                }
            result = classifier(input.text or "")

        label, score = _extract_label_score(result)
        _record_metrics(label, score, start)
        return normalize_output(result)
    except Exception as e:
        return JSONResponse(status_code=400, content={"error": str(e)})
    finally:
        if tmp_path:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
