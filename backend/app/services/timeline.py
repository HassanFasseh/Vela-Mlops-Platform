import requests
import time

PROMETHEUS_URL = "http://monitoring-kube-prometheus-prometheus.monitoring.svc.cluster.local:9090"

def query_range(promql: str, start: float, end: float, step: str = "30s"):
    resp = requests.get(
        f"{PROMETHEUS_URL}/api/v1/query_range",
        params={"query": promql, "start": start, "end": end, "step": step},
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json()["data"]["result"]

def build_timeline(window_minutes: int = 360):
    end = time.time()
    start = end - (window_minutes * 60)

    events = []

    deploy_series = query_range('process_start_time_seconds{job="model-service"}', start, end)
    seen_starts = set()
    for series in deploy_series:
        for ts, val in series["values"]:
            start_time = float(val)
            if start_time not in seen_starts and start <= start_time <= end:
                seen_starts.add(start_time)
                events.append({"timestamp": start_time, "type": "deploy", "detail": "model-service pod started"})

    drift_series = query_range("drift_score", start, end)
    for series in drift_series:
        for ts, val in series["values"]:
            score = float(val)
            if score > 0:
                events.append({"timestamp": float(ts), "type": "drift", "detail": f"drift_score={score:.3f}"})

    latency_series = query_range("histogram_quantile(0.95, rate(prediction_latency_seconds_bucket[5m]))", start, end)
    for series in latency_series:
        for ts, val in series["values"]:
            try:
                latency = float(val)
            except ValueError:
                continue
            if latency != latency:  # NaN check — NaN is the only float that doesn't equal itself
                continue
            if latency != latency:  # NaN check
                continue
            events.append({"timestamp": float(ts), "type": "latency_p95", "detail": f"{latency*1000:.1f}ms"})

    events.sort(key=lambda e: e["timestamp"])
    return events

def query_instant(promql: str) -> float:
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
        return 0.0
    except Exception:
        return 0.0

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

def build_metrics_summary() -> dict:
    return {
        "predictions_total": query_instant('predictions_total{job="model-service"}'),
        "prediction_rate_5m": query_instant('rate(predictions_total{job="model-service"}[5m]) * 60'),
        "latency_p95": query_instant('histogram_quantile(0.95, rate(prediction_latency_seconds_bucket{job="model-service"}[5m]))'),
        "drift_score": query_instant("drift_score"),
        "drift_history": query_range_values("drift_score", window_minutes=120),
        "node_cpu_percent": query_instant('100 - (avg(rate(node_cpu_seconds_total{mode="idle"}[5m])) * 100)'),
        "node_memory_used_gb": query_instant('(node_memory_MemTotal_bytes - node_memory_MemAvailable_bytes) / 1024^3'),
        "node_memory_total_gb": query_instant('node_memory_MemTotal_bytes / 1024^3'),
    }
