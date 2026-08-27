"""
Per-deployment drift tracking.

model-service/main.py runs Evidently drift detection on its own
prediction history, but that code is hardcoded into that one service —
every other deployment (other HuggingFace models via model-runner, every
custom model) has no equivalent at all. This moves the same idea into
the backend, keyed by deployment_id in Redis, so it applies uniformly:
any deployment gets drift detection automatically the moment predictions
start flowing through POST /api/v1/predict, regardless of task type or
whether it's a HuggingFace or custom model.

Redis keys (namespaced per deployment, unlike model-service's own fixed
"model_service:..." keys):
    drift:{deployment_id}:current    JSON list of rows collected since
                                      the last rotation (see below)
    drift:{deployment_id}:reference  JSON list of rows from the
                                      previous window, used as the
                                      comparison baseline
    drift:{deployment_id}:result     JSON {"drift_share", "columns",
                                      "computed_at"} — the latest
                                      computation only, not a history
                                      (there's no per-deployment time
                                      series stored here the way
                                      Prometheus's drift_score gauge
                                      gives model-service one)

Each row is {"label", "score", "text_length"} — the same three fields
model-service's own compute_drift() has always used, except label is
left as whatever string came back rather than encoded 0/1, since an
arbitrary deployment's label vocabulary isn't fixed to positive/negative
the way model-service's sentiment output is; Evidently treats a string
column as categorical on its own.

Window mechanics: `current` grows by one row per successful prediction.
Every CHECK_EVERY rows (default 30) — and only once a `reference` window
actually exists — a drift comparison runs and its result is stored. Once
`current` reaches WINDOW_SIZE rows (default 100), it becomes the new
`reference` and `current` resets to empty, so the reference baseline
keeps sliding forward instead of staying fixed to whatever the first 100
predictions ever looked like.

Every public function here fails soft: Redis being unreachable, or
Evidently erroring on a malformed/too-small window, is logged and
swallowed rather than raised — this is telemetry, not something that
should ever break an actual prediction request. Imports of redis/
pandas/evidently are deliberately lazy (inside functions, not at module
load) so importing this module never fails even before a backend image
that has them in its requirements.txt has actually been rebuilt/rolled
out.
"""

import os
import json
import time
import logging

logger = logging.getLogger("drift_tracker")

REDIS_HOST = os.environ.get("REDIS_HOST", "redis.default.svc.cluster.local")
REDIS_PORT = 6379

# "Every 30 predictions" / "after 100 predictions" from the request this
# shipped from — kept as named, overridable constants rather than
# hardcoded at each call site.
CHECK_EVERY = int(os.environ.get("DRIFT_CHECK_EVERY", "30"))
WINDOW_SIZE = int(os.environ.get("DRIFT_WINDOW_SIZE", "100"))

_client = None
_client_failed = False


def _get_client():
    """A single lazily-created, cached Redis client — re-attempted only
    if it was never successfully created (not retried forever on every
    call once confirmed unreachable, to avoid a slow connect attempt on
    the hot path of every single prediction)."""
    global _client, _client_failed
    if _client is not None:
        return _client
    if _client_failed:
        return None
    try:
        import redis
        client = redis.Redis(
            host=REDIS_HOST, port=REDIS_PORT, decode_responses=True,
            socket_connect_timeout=2, socket_timeout=2,
        )
        client.ping()
        _client = client
        return _client
    except Exception as e:
        _client_failed = True
        logger.warning(f"[drift_tracker] Redis unavailable at {REDIS_HOST}:{REDIS_PORT}, drift tracking disabled: {e}")
        return None


def _current_key(deployment_id):
    return f"drift:{deployment_id}:current"


def _reference_key(deployment_id):
    return f"drift:{deployment_id}:reference"


def _result_key(deployment_id):
    return f"drift:{deployment_id}:result"


def _extract_row(result, text_length):
    """Best-effort label/score out of whatever POST /api/v1/predict's
    downstream model returned — every shape that endpoint's three
    branches (model-runner's sentiment/zero-shot/generic, and custom-
    runner) actually produce:
      {"label": ..., "score": ...}                     sentiment, text-classification
      {"labels": [...], "scores": [...], ...}           zero-shot
      {"result": {...} or [{...}, ...] or "..."}        model-runner's generic branch
      anything else (custom-runner's own, unconstrained) convention only
    None for either field (not a fabricated value) when nothing usable
    is found — Evidently just sees one fewer real column for that row."""
    candidate = result
    if isinstance(result, dict) and "result" in result:
        candidate = result["result"]
    if isinstance(candidate, list) and len(candidate) >= 1:
        candidate = candidate[0]

    label, score = None, None
    if isinstance(candidate, dict):
        if candidate.get("label") is not None:
            label = candidate.get("label")
        elif isinstance(candidate.get("labels"), list) and candidate["labels"]:
            label = candidate["labels"][0]

        if candidate.get("score") is not None:
            score = candidate.get("score")
        elif isinstance(candidate.get("scores"), list) and candidate["scores"]:
            score = candidate["scores"][0]

    try:
        score = float(score) if score is not None else None
    except (TypeError, ValueError):
        score = None

    return {"label": str(label) if label is not None else None, "score": score, "text_length": text_length}


def _compute_and_store(client, deployment_id, reference, current):
    try:
        import pandas as pd
        from evidently import Report
        from evidently.presets import DataDriftPreset

        ref_df = pd.DataFrame(reference)
        cur_df = pd.DataFrame(current)
        report = Report(metrics=[DataDriftPreset()])
        result = report.run(reference_data=ref_df, current_data=cur_df)
        result_dict = result.dict()
        drift_share = result_dict["metrics"][0]["value"]["share"]

        columns = []
        for metric in result_dict["metrics"][1:]:
            col_name = metric["config"].get("column", "unknown")
            p_value = float(metric["value"]) if metric["value"] is not None else 1.0
            columns.append({
                "column": col_name,
                "p_value": round(p_value, 4),
                "drifted": p_value < 0.05,
                "method": metric["config"].get("method", "unknown"),
            })

        client.set(_result_key(deployment_id), json.dumps({
            "drift_share": drift_share,
            "columns": columns,
            "computed_at": time.time(),
        }))
        logger.info(f"[drift_tracker] deployment {deployment_id}: drift_share={drift_share}")
    except Exception as e:
        logger.warning(f"[drift_tracker] drift computation failed for deployment {deployment_id}: {e}")


def record_prediction(deployment_id, result, text_length: int = 0):
    """Called after every successful POST /api/v1/predict response is
    prepared. Never raises."""
    if deployment_id is None:
        return
    client = _get_client()
    if client is None:
        return
    try:
        row = _extract_row(result, text_length)

        cur_key = _current_key(deployment_id)
        raw_current = client.get(cur_key)
        current = json.loads(raw_current) if raw_current else []
        current.append(row)
        client.set(cur_key, json.dumps(current))

        if len(current) > 0 and len(current) % CHECK_EVERY == 0:
            raw_reference = client.get(_reference_key(deployment_id))
            reference = json.loads(raw_reference) if raw_reference else []
            if reference:
                _compute_and_store(client, deployment_id, reference, current)

        if len(current) >= WINDOW_SIZE:
            client.set(_reference_key(deployment_id), json.dumps(current))
            client.set(cur_key, json.dumps([]))
    except Exception as e:
        logger.warning(f"[drift_tracker] record_prediction failed for deployment {deployment_id}: {e}")


def get_drift_result(deployment_id) -> dict:
    """GET /metrics-summary's deployment_id path reads this instead of
    model-service's hardcoded /drift-details. {"drift_share": None, ...}
    (not 0.0) when nothing's been computed yet or Redis is unreachable —
    "no data" stays distinguishable from "computed and reading zero",
    same convention services/timeline.py's _safe() uses."""
    client = _get_client()
    if client is not None:
        try:
            raw = client.get(_result_key(deployment_id))
            if raw:
                return json.loads(raw)
        except Exception as e:
            logger.warning(f"[drift_tracker] get_drift_result failed for deployment {deployment_id}: {e}")
    return {"drift_share": None, "columns": [], "computed_at": None}
