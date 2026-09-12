/*
 * Vela DEMO MODE - client-side only, opt-in via ?demo=1 in THIS page's URL.
 *
 * Fabricates realistic-looking responses for a fixed allowlist of metric/
 * catalog GET endpoints so the Monitoring/Drift and Infrastructure screens
 * render populated instead of "No telemetry yet" - for local screenshots.
 * Nothing here ever touches the backend: no server code path changes for
 * this feature at all, anywhere.
 *
 * Scoped by construction, three separate ways:
 *   1. This <script> tag is only included on /admin/monitoring and
 *      /admin/infrastructure (see admin_pages.py) - it is never shipped to
 *      any member-facing page or loaded anywhere by default.
 *   2. Even loaded, the entire IIFE below is a no-op - Api.get is never
 *      reassigned - unless ?demo=1 is present in location.search at the
 *      moment THIS script runs. No flag in the URL, zero footprint.
 *   3. Even with the flag on, only an exact allowlist of 6 GET paths
 *      (ALLOWLIST_PATHS below) is ever intercepted. Api.post/patch/del and
 *      Api.request itself are completely untouched, so auth (login, and
 *      the /auth/me check Api.requireAuth() runs on every page load) and
 *      every mutation (deploy, create team, change password, ...) always
 *      hit the real backend, demo mode or not.
 *
 * Seeded story (DEMO_MODELS below): fraud-detector-v3 is healthy, churn-
 * predictor is drifting (rising drift score across whichever window is
 * requested), legacy-nps-scorer is failing/degraded (down replica, low
 * confidence, elevated latency). Values are deterministic - a seeded hash,
 * not Math.random() - so a chart's shape stays stable across the 30s poll
 * instead of visibly jittering on every refresh.
 */
(function () {
  "use strict";

  function isDemoOn() {
    try {
      return new URLSearchParams(location.search).get("demo") === "1";
    } catch (e) {
      return false;
    }
  }

  if (!isDemoOn()) return; // flag not present on this page's URL - do not touch Api.get at all

  // ---- deterministic pseudo-noise (no Math.random - same shape every poll) --
  function hash01(seed) {
    const x = Math.sin(seed * 12.9898 + 78.233) * 43758.5453;
    return x - Math.floor(x); // [0, 1)
  }
  function noise(seed, amp) {
    return (hash01(seed) * 2 - 1) * amp; // [-amp, amp]
  }
  function lerp(a, b, t) {
    return a + (b - a) * t;
  }
  function round(n, dec) {
    const f = Math.pow(10, dec);
    return Math.round(n * f) / f;
  }
  function nowSec() {
    return Date.now() / 1000;
  }

  const DEMO_JOB = "monitoring/platform-runner-podmonitor";

  // range: [value at start of the requested window, value "now"] - every
  // series/event generator below interpolates linearly across that range by
  // fraction-through-the-window, so "drift rising over time" is just
  // range.drift[0] < range.drift[1], read the same way at any window length.
  const DEMO_MODELS = [
    {
      id: -101,
      name: "fraud-detector-v3",
      task: "text-classification",
      story: "healthy",
      deployStatus: "running", ready: 2, desired: 2, liveStatus: "online",
      range: { rate: [56, 52], latency: [0.088, 0.098], confidence: [0.965, 0.955], drift: [0.04, 0.05] },
      driftColumns: [
        { column: "text_length", p_value: 0.71, drifted: false, method: "ks" },
        { column: "confidence", p_value: 0.64, drifted: false, method: "ks" },
      ],
      summary: "Predictions are flowing at a steady rate with no drift detected in the current window - latency and confidence have both stayed within their normal range.",
    },
    {
      id: -102,
      name: "churn-predictor",
      task: "text-classification",
      story: "drifting",
      deployStatus: "running", ready: 2, desired: 2, liveStatus: "online",
      range: { rate: [44, 39], latency: [0.101, 0.137], confidence: [0.90, 0.79], drift: [0.14, 0.74] },
      driftColumns: [
        { column: "label", p_value: 0.012, drifted: true, method: "chi2" },
        { column: "score", p_value: 0.021, drifted: true, method: "ks" },
        { column: "text_length", p_value: 0.41, drifted: false, method: "ks" },
      ],
      summary: "Drift has been rising across the current window and now affects a majority of tracked features - this coincides with a gradual drop in average prediction confidence, though a direct cause can't be confirmed from this data alone.",
    },
    {
      id: -103,
      name: "legacy-nps-scorer",
      task: "text-classification",
      story: "degraded",
      deployStatus: "failed", ready: 0, desired: 1, liveStatus: "offline",
      range: { rate: [7, 4], latency: [0.42, 0.63], confidence: [0.66, 0.55], drift: [0.22, 0.36] },
      driftColumns: [
        { column: "label", p_value: 0.034, drifted: true, method: "chi2" },
        { column: "text_length", p_value: 0.18, drifted: false, method: "ks" },
      ],
      summary: "This deployment is showing elevated latency alongside reduced prediction confidence and moderate feature drift - traffic volume is low, which may make these readings less stable than a higher-traffic deployment's.",
    },
  ];

  function valueAt(model, key, frac, seedExtra) {
    const [a, b] = model.range[key];
    const v = lerp(a, b, frac);
    return v + noise(model.id * 97 + seedExtra, Math.abs(b - a || a) * 0.06 + 0.003);
  }

  function findByPod(pod) {
    if (!pod) return null;
    return DEMO_MODELS.find((m) => pod.indexOf(m.name) === 0) || null;
  }
  function findModel(params) {
    const depId = params.get("deployment_id");
    if (depId) {
      const idNum = parseInt(depId, 10);
      const byId = DEMO_MODELS.find((m) => m.id === idNum);
      if (byId) return byId;
    }
    return findByPod(params.get("pod"));
  }

  // ---- /metrics-summary ---------------------------------------------------
  function nodeCpuPercent() {
    return round(41 + 6 * Math.sin(nowSec() / 600) + noise(1, 1.2), 1);
  }
  function nodeMemUsedGb() {
    return round(9.3 + 0.5 * Math.sin(nowSec() / 900) + noise(2, 0.08), 2);
  }

  function series(model, key, minutes, points) {
    const now = nowSec();
    const step = (minutes * 60) / (points - 1);
    const out = [];
    for (let i = 0; i < points; i++) {
      const frac = i / (points - 1);
      out.push([now - (points - 1 - i) * step, valueAt(model, key, frac, i)]);
    }
    return out;
  }

  function metricsSummaryFor(model) {
    const points = 61;
    const minutes = 120;
    const rateHist = series(model, "rate", minutes, points).map((p) => [p[0], round(Math.max(0, p[1]), 2)]);
    const latHist = series(model, "latency", minutes, points).map((p) => [p[0], round(Math.max(0.01, p[1]), 4)]);
    const confHist = series(model, "confidence", minutes, points).map((p) => [p[0], round(Math.min(0.999, Math.max(0.02, p[1])), 4)]);
    const driftHist = series(model, "drift", minutes, points).map((p) => [p[0], round(Math.min(0.98, Math.max(0, p[1])), 4)]);
    const last = (h) => h[h.length - 1][1];
    return {
      job: DEMO_JOB,
      pod: model.name + "-.*",
      deployment_id: model.id,
      predictions_total: Math.round(20000 + Math.abs(model.id) * 40 + last(rateHist) * 600),
      prediction_rate_5m: last(rateHist),
      prediction_rate_history: rateHist,
      latency_p95: last(latHist),
      latency_p95_history: latHist,
      prediction_confidence: last(confHist),
      prediction_confidence_history: confHist,
      drift_score: last(driftHist),
      drift_history: driftHist,
      drift_details: { drift_share: last(driftHist), columns: model.driftColumns, computed_at: nowSec() - 90 },
      node_cpu_percent: nodeCpuPercent(),
      node_memory_used_gb: nodeMemUsedGb(),
      node_memory_total_gb: 16,
    };
  }

  // No model resolved (e.g. Infrastructure's bare `/metrics-summary` with no
  // job/pod/deployment_id at all) - node stats still populate, per-model
  // fields stay honestly null/empty exactly like the real fail-soft shape.
  function metricsSummaryGlobal() {
    return {
      job: null, pod: null, deployment_id: null,
      predictions_total: null, prediction_rate_5m: null, prediction_rate_history: [],
      latency_p95: null, latency_p95_history: [],
      prediction_confidence: null, prediction_confidence_history: [],
      drift_score: null, drift_history: [],
      drift_details: { drift_share: null, columns: [], computed_at: null },
      node_cpu_percent: nodeCpuPercent(),
      node_memory_used_gb: nodeMemUsedGb(),
      node_memory_total_gb: 16,
    };
  }

  // ---- /timeline ------------------------------------------------------------
  function timelineFor(model, windowMinutes) {
    const now = nowSec();
    const deployFrac = 0.03; // deploy event near the start of the window
    const events = [{ timestamp: now - (1 - deployFrac) * windowMinutes * 60, type: "deploy", detail: DEMO_JOB + " pod started" }];

    const latPoints = Math.max(3, Math.min(24, Math.round(windowMinutes / 25)));
    for (let i = 0; i < latPoints; i++) {
      const frac = i / (latPoints - 1);
      if (frac < deployFrac) continue;
      const v = Math.max(0.01, valueAt(model, "latency", frac, 500 + i));
      events.push({ timestamp: now - (1 - frac) * windowMinutes * 60, type: "latency_p95", detail: (v * 1000).toFixed(1) + "ms" });
    }

    if (model.story !== "healthy") {
      const driftPoints = Math.max(3, Math.min(16, Math.round(windowMinutes / 40)));
      for (let i = 0; i < driftPoints; i++) {
        const frac = i / (driftPoints - 1);
        if (frac < deployFrac) continue;
        const score = Math.max(0, valueAt(model, "drift", frac, 900 + i));
        if (score > 0) events.push({ timestamp: now - (1 - frac) * windowMinutes * 60, type: "drift", detail: "drift_score=" + score.toFixed(3) });
      }
    }
    events.sort((a, b) => a.timestamp - b.timestamp);
    return events;
  }

  // No model resolved (Infrastructure's "uptime since last deploy" reads
  // `/timeline?window_minutes=1440` with no job/pod at all) - union every
  // demo model's events so the most recent deploy across all three wins,
  // same as the real endpoint would across every real Deployment.
  function timelineGlobal(windowMinutes) {
    const all = [];
    DEMO_MODELS.forEach((m) => all.push.apply(all, timelineFor(m, windowMinutes)));
    all.sort((a, b) => a.timestamp - b.timestamp);
    return all;
  }

  // ---- /models/status, /deployments, /admin/deployment-registry -----------
  function modelsStatusAll() {
    return DEMO_MODELS.map((m) => ({ id: m.id, name: m.name, task: m.task, job: DEMO_JOB, instrumented: true, status: m.liveStatus, model: m.name }));
  }
  function deploymentsAll() {
    return DEMO_MODELS.map((m) => ({ name: m.name, model_name: m.name, task_type: m.task, status: m.deployStatus, ready: m.ready, desired: m.desired }));
  }
  function registryAll() {
    return DEMO_MODELS.map((m) => ({ id: m.id, name: m.name, model_name: m.name, task_type: m.task, model_type: "huggingface", status: m.deployStatus, is_active: true, workspace_id: null }));
  }

  // ---- dispatch -------------------------------------------------------------
  const ALLOWLIST_PATHS = ["/metrics-summary", "/summary", "/timeline", "/models/status", "/deployments", "/admin/deployment-registry"];

  function respond(pathname, params) {
    if (pathname === "/metrics-summary") {
      const m = findModel(params);
      return m ? metricsSummaryFor(m) : metricsSummaryGlobal();
    }
    if (pathname === "/timeline") {
      const minutes = parseInt(params.get("window_minutes") || "360", 10) || 360;
      const m = findModel(params);
      return m ? timelineFor(m, minutes) : timelineGlobal(minutes);
    }
    if (pathname === "/summary") {
      const m = findModel(params);
      return { summary: m ? m.summary : "No demo data for this selection." };
    }
    if (pathname === "/models/status") return modelsStatusAll();
    if (pathname === "/deployments") return deploymentsAll();
    if (pathname === "/admin/deployment-registry") return registryAll();
    return undefined; // unreachable given the allowlist check below
  }

  // Wrap Api.get ONLY - Api.post/patch/del/request (every mutation, and the
  // shared request() helper login/auth run through) are left completely
  // alone. A path outside ALLOWLIST_PATHS (including /auth/me, called by
  // Api.requireAuth() on every single page load) falls straight through to
  // the real network call, unchanged.
  const realGet = Api.get;
  Api.get = function (path) {
    try {
      const url = new URL(path, location.origin);
      if (ALLOWLIST_PATHS.indexOf(url.pathname) !== -1) {
        return Promise.resolve(respond(url.pathname, url.searchParams));
      }
    } catch (e) {
      /* malformed path - fall through to the real request below */
    }
    return realGet(path);
  };

  // ---- visible-but-disposable "demo data" indicator ------------------------
  // A floating corner pill, never drawn onto a Chart.js canvas - it's a
  // plain DOM element cornered for easy cropping, and click-to-dismiss for a
  // clean screenshot without needing to crop at all.
  function injectBadge() {
    if (document.getElementById("vela-demo-badge")) return;
    const el = document.createElement("div");
    el.id = "vela-demo-badge";
    el.title = "Demo mode - every number on this page is fabricated. Click to hide.";
    el.textContent = "● Demo data";
    el.style.cssText = [
      "position:fixed", "right:12px", "bottom:12px", "z-index:99999",
      "background:var(--surface-raised,#1a1a1e)", "border:1px solid var(--warning-border,rgba(210,164,34,.4))",
      "color:var(--warning-fg,#d2a422)", "font:500 11px var(--font-sans,sans-serif)",
      "letter-spacing:.04em", "text-transform:uppercase",
      "padding:5px 10px", "border-radius:var(--radius-full,999px)", "cursor:pointer",
      "box-shadow:var(--shadow-md,0 4px 12px rgba(0,0,0,.35))", "user-select:none",
    ].join(";");
    el.addEventListener("click", function () { el.remove(); });
    document.body.appendChild(el);
  }

  if (document.body) injectBadge();
  else document.addEventListener("DOMContentLoaded", injectBadge);
})();
