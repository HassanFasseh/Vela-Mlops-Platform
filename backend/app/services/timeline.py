import requests
import time

import os
PROMETHEUS_URL = os.environ.get("PROMETHEUS_URL", "http://monitoring-kube-prometheus-prometheus.monitoring.svc.cluster.local:9090")

# The Prometheus job model-service is scraped under (k8s/model-service-
# monitor.yaml's ServiceMonitor selects app=model-service only, and only
# it). Kept as a named default rather than hardcoded at each call site so
# build_metrics_summary()/build_timeline() can be pointed at a different
# job, without silently reverting to "whichever series Prometheus happens
# to return first" the way the old unscoped `drift_score` query did.
#
# Every model-runner/custom-runner pod (k8s/platform-runner-podmonitor.yaml)
# reports a *different* job value: "monitoring/platform-runner-
# podmonitor" — the PodMonitor's own namespace/name, not anything per-
# deployment, since a PodMonitor (unlike model-service's one-target
# ServiceMonitor) covers every dynamically-named deployment with a single
# resource. `job` alone can't disambiguate between them; `pod` (matched
# with a regex against the deployment-name prefix every pod name carries
# — see _selector()) does.
DEFAULT_JOB = "model-service"

def _esc(value: str) -> str:
    """Minimal PromQL string-literal escaping for a label value that
    ultimately comes from a query param (job/pod) — this codebase already
    interpolates both straight into PromQL text rather than using
    Prometheus's parameterized query support (which doesn't exist), so
    this is a backstop against a value breaking out of its quotes, not a
    claim of full PromQL-injection safety."""
    return str(value).replace("\\", "\\\\").replace('"', '\\"')

def _selector(job: str, pod: str = None) -> str:
    """{job="..."} or, when scoping to one deployment behind a shared
    PodMonitor job, {job="...",pod=~"..."}."""
    if pod:
        return f'{{job="{_esc(job)}",pod=~"{_esc(pod)}"}}'
    return f'{{job="{_esc(job)}"}}'

def query_range(promql: str, start: float, end: float, step: str = "30s"):
    resp = requests.get(
        f"{PROMETHEUS_URL}/api/v1/query_range",
        params={"query": promql, "start": start, "end": end, "step": step},
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json()["data"]["result"]

def build_timeline(window_minutes: int = 360, job: str = DEFAULT_JOB, pod: str = None):
    end = time.time()
    start = end - (window_minutes * 60)
    sel = _selector(job, pod)

    events = []

    deploy_series = query_range(f'process_start_time_seconds{sel}', start, end)
    seen_starts = set()
    for series in deploy_series:
        for ts, val in series["values"]:
            start_time = float(val)
            if start_time not in seen_starts and start <= start_time <= end:
                seen_starts.add(start_time)
                events.append({"timestamp": start_time, "type": "deploy", "detail": f"{job} pod started"})

    # drift_score is only ever computed by model-service (see
    # model-service/main.py:compute_drift()) — every other job (including
    # every model-runner/custom-runner deployment behind the shared
    # platform-runner-podmonitor job) has no such gauge, so this
    # legitimately comes back empty for them rather than picking up
    # model-service's series regardless of which model is selected.
    drift_series = query_range(f'drift_score{sel}', start, end)
    for series in drift_series:
        for ts, val in series["values"]:
            score = float(val)
            if score > 0:
                events.append({"timestamp": float(ts), "type": "drift", "detail": f"drift_score={score:.3f}"})

    latency_series = query_range(f'histogram_quantile(0.95, rate(prediction_latency_seconds_bucket{sel}[5m]))', start, end)
    for series in latency_series:
        for ts, val in series["values"]:
            try:
                latency = float(val)
            except ValueError:
                continue
            if latency != latency:  # NaN check — NaN is the only float that doesn't equal itself
                continue
            events.append({"timestamp": float(ts), "type": "latency_p95", "detail": f"{latency*1000:.1f}ms"})

    events.sort(key=lambda e: e["timestamp"])
    return events

def query_instant(promql: str):
    """Returns None when Prometheus has no data for this query — distinct
    from a real measured 0.0 — so callers (and the UI) can tell "no data"
    apart from "instrumented and reading zero"."""
    try:
        import requests, time
        resp = requests.get(
            f"{PROMETHEUS_URL}/api/v1/query",
            params={"query": promql, "time": time.time()},
            timeout=5,
        )
        resp.raise_for_status()
        result = resp.json()["data"]["result"]
        if result:
            return float(result[0]["value"][1])
        return None
    except Exception:
        return None

def query_range_values(promql: str, window_minutes: int = 60) -> list:
    import time
    end = time.time()
    start = end - (window_minutes * 60)
    try:
        series = query_range(promql, start, end, step="60s")
        if series:
            return [[float(ts), float(val)] for ts, val in series[0]["values"] if val != "NaN"]
        return []
    except Exception:
        return []

def _safe(v):
    """NaN/Inf (e.g. a rate() with too few samples yet) is "not enough
    data", same as a query with no result at all — normalized to None so
    every "no data" case looks the same to callers. A real 0.0 is passed
    through unchanged."""
    import math
    if v is None:
        return None
    if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
        return None
    return v

def get_drift_details() -> dict:
    """Get population-level drift breakdown from model-service. There is
    exactly one drift pipeline in this backend (model-service's Evidently
    report) — this always reflects that one service, regardless of which
    job metrics-summary/timeline were asked about, and build_metrics_
    summary() below only attaches it when job == "model-service"."""
    import os
    model_url = os.environ.get("MODEL_SERVICE_URL", "http://model-service.default.svc.cluster.local")
    try:
        import requests as req
        r = req.get(f"{model_url}/drift-details", timeout=3)
        return r.json()
    except Exception:
        return {"drift_share": 0.0, "columns": [], "computed_at": None}

def build_metrics_summary(job: str = DEFAULT_JOB, pod: str = None) -> dict:
    has_drift = job == "model-service"  # see get_drift_details() docstring
    sel = _selector(job, pod)
    return {
        "job": job,
        "pod": pod,
        "predictions_total": _safe(query_instant(f'predictions_total{sel}')),
        "prediction_rate_5m": _safe(query_instant(f'rate(predictions_total{sel}[5m]) * 60')),
        "prediction_rate_history": [[p[0], _safe(p[1])] for p in query_range_values(f'rate(predictions_total{sel}[5m]) * 60', window_minutes=120)],
        "latency_p95": _safe(query_instant(f'histogram_quantile(0.95, rate(prediction_latency_seconds_bucket{sel}[5m]))')),
        "latency_p95_history": [[p[0], _safe(p[1])] for p in query_range_values(f'histogram_quantile(0.95, rate(prediction_latency_seconds_bucket{sel}[5m]))', window_minutes=120)],
        # Gauge, not a histogram — model-runner/custom-runner set this to
        # the most recent prediction's confidence score (see their
        # main.py). model-service predates that instrumentation and
        # doesn't export it at all, so this legitimately comes back None
        # for job="model-service" — not fabricated as 0.
        "prediction_confidence": _safe(query_instant(f'prediction_confidence{sel}')),
        "prediction_confidence_history": [[p[0], _safe(p[1])] for p in query_range_values(f'prediction_confidence{sel}', window_minutes=120)],
        "drift_score": _safe(query_instant(f'drift_score{sel}')) if has_drift else None,
        "drift_history": [[p[0], _safe(p[1])] for p in query_range_values(f'drift_score{sel}', window_minutes=120)] if has_drift else [],
        "drift_details": get_drift_details() if has_drift else {"drift_share": None, "columns": [], "computed_at": None},
        # Node-wide, not job-scoped — real system metrics, kept here only
        # because /admin/infrastructure already reads this endpoint for
        # them. Not shown on the model-centric Monitoring/Drift pages.
        "node_cpu_percent": _safe(query_instant('100 - (avg(rate(node_cpu_seconds_total{mode="idle"}[5m])) * 100)')),
        "node_memory_used_gb": _safe(query_instant('(node_memory_MemTotal_bytes - node_memory_MemAvailable_bytes) / 1024^3')),
        "node_memory_total_gb": _safe(query_instant('node_memory_MemTotal_bytes / 1024^3')),
    }
