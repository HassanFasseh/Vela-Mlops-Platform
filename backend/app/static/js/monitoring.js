/*
 * Vela Model Health — model-centric (spec redesign). Shared by
 * /admin/monitoring and /app/monitoring via Monitoring.start({role}).
 *
 * Selection comes from ModelCatalog (models.js). Whether a model actually
 * has performance data is a runtime fact, checked on every fetch
 * (metricsHaveData()) rather than assumed up front from what kind of
 * model it is — model-runner and custom-runner deployments got real
 * Prometheus instrumentation too (see model-runner/main.py, custom-
 * runner/base/main.py), so any of them can have data once they've
 * actually served predictions and Prometheus has scraped them. No data
 * yet (or no resolvable job at all — see entry.job) shows the same
 * honest "make some predictions and check back" panel regardless of
 * model kind, and clears itself on the next poll once data shows up.
 * See drift.js for the linked full drift analysis.
 *
 * The performance grid's DOM (canvases) is only (re)built when the
 * selected model or its no-data/has-data state actually changes (see
 * performanceBuiltFor) — the 30s poll just calls setChartData()/
 * setDriftScoreData() on the existing Chart.js instances. Rebuilding the
 * canvases on every poll while reusing the same chart objects (the
 * previous bug here) leaves each chart pointing at a detached canvas
 * after the first refresh, since a fresh, blank one replaces it in the
 * DOM — the chart doesn't error, it just silently never draws into the
 * new element again.
 *
 * Expects in the page: #model-picker #model-empty #model-content
 *   #mh-name #mh-task #mh-status-badge #mh-status-stats
 *   #mh-performance #mh-drift-link #mh-drift-teaser
 *   #summary-box #timeline-status #timeline-list
 */

const Monitoring = (() => {
  let role = "member";
  let entries = [];
  let selectedKey = null;
  let pollHandle = null;
  let predictionsChart = null;
  let latencyChart = null;
  let driftScoreChart = null;
  let confidenceChart = null;
  let performanceBuiltFor = null; // entry.key, or "no-data:<key>" — see loadPerformance()
  let verdictState = { status: null, drifted: null, rate: null }; // see renderVerdict()

  function fmtN(n, dec = 1) {
    return n == null || isNaN(n) ? "—" : Number(n).toFixed(dec);
  }

  function median(values) {
    const v = values.filter((x) => x != null && !isNaN(x)).slice().sort((a, b) => a - b);
    if (!v.length) return null;
    const mid = Math.floor(v.length / 2);
    return v.length % 2 ? v[mid] : (v[mid - 1] + v[mid]) / 2;
  }

  function statLine(value, label, muted) {
    return (
      '<div class="stat-line"><div class="stat-line-value' + (muted ? " is-muted" : "") + '">' +
      UI.escapeHtml(String(value)) + "</div><div class=\"stat-line-label\">" + UI.escapeHtml(label) + "</div></div>"
    );
  }

  function customPhaseLabel(phase) {
    return { downloading: "Downloading model files", provisioning: "Starting", running: "Running", failed: "Failed", unknown: "Unknown" }[phase] || phase;
  }

  function customPhaseVariant(phase) {
    if (phase === "running") return "success";
    if (phase === "failed") return "danger";
    if (phase === "unknown") return "neutral";
    return "warning";
  }

  /* ---- A small Chart.js plugin: vertical dashed markers for deploy
     events, positioned against the chart's own (rawTimestamps) array
     rather than a real time scale — labels here are formatted strings,
     not a linear/time axis, so markers are matched to the nearest
     sampled point instead of an exact pixel-perfect timestamp. Good
     enough for "roughly when did this deploy happen relative to the
     trend", which is the actual question this answers. ------------- */
  const deployMarkerPlugin = {
    id: "deployMarkers",
    afterDatasetsDraw(chart) {
      const marks = chart.config._deployMarks;
      const raw = chart.config._rawTimestamps;
      if (!marks || !marks.length || !raw || !raw.length) return;
      const xScale = chart.scales.x;
      const yScale = chart.scales.y;
      if (!xScale || !yScale) return;
      const ctx = chart.ctx;
      ctx.save();
      ctx.strokeStyle = "#8a8a9a";
      ctx.setLineDash([3, 3]);
      ctx.lineWidth = 1;
      marks.forEach((ts) => {
        let nearest = 0;
        let best = Infinity;
        raw.forEach((t, i) => {
          const d = Math.abs(t - ts);
          if (d < best) {
            best = d;
            nearest = i;
          }
        });
        const x = xScale.getPixelForValue(nearest);
        ctx.beginPath();
        ctx.moveTo(x, yScale.top);
        ctx.lineTo(x, yScale.bottom);
        ctx.stroke();
      });
      ctx.restore();
    },
  };

  function makeLineChart(canvasId, color) {
    const ctx = document.getElementById(canvasId);
    if (!ctx || !window.Chart) return null;
    return new Chart(ctx.getContext("2d"), {
      type: "line",
      // Registered per-chart-instance rather than globally via
      // Chart.register() — avoids any ordering/duplicate-registration
      // concerns from re-running this module's top-level code.
      plugins: [deployMarkerPlugin],
      data: {
        labels: [],
        datasets: [
          { label: "value", data: [], borderColor: color, backgroundColor: "transparent", borderWidth: 1.5, pointRadius: 0, tension: 0.2 },
          { label: "baseline (median)", data: [], borderColor: "#8a8a9a", borderDash: [4, 3], borderWidth: 1, pointRadius: 0 },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        animation: false,
        plugins: { legend: { display: false } },
        scales: {
          x: { display: false },
          y: { beginAtZero: true, ticks: { font: { size: 10 } }, grid: { color: "rgba(128,128,128,0.12)" } },
        },
      },
    });
  }

  function makeDriftScoreChart(canvasId) {
    const ctx = document.getElementById(canvasId);
    if (!ctx || !window.Chart) return null;
    return new Chart(ctx.getContext("2d"), {
      type: "line",
      data: { labels: [], datasets: [{ label: "Drift share", data: [], borderColor: "#dc2626", backgroundColor: "rgba(220,38,38,0.08)", borderWidth: 1.5, pointRadius: 0, fill: true, tension: 0.25 }] },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        animation: false,
        plugins: { legend: { display: false } },
        scales: {
          x: { display: false },
          y: { min: 0, max: 1, ticks: { font: { size: 10 } }, grid: { color: "rgba(128,128,128,0.12)" } },
        },
      },
    });
  }

  function setChartData(chart, series, deployTimestamps) {
    if (!chart) return;
    chart.data.labels = series.map((p) => new Date(p[0] * 1000).toLocaleTimeString());
    chart.data.datasets[0].data = series.map((p) => p[1]);
    const base = median(series.map((p) => p[1]));
    chart.data.datasets[1].data = series.map(() => base);
    chart.config._rawTimestamps = series.map((p) => p[0]);
    chart.config._deployMarks = deployTimestamps || [];
    chart.update("none");
  }

  function setDriftScoreData(chart, series) {
    if (!chart) return;
    chart.data.labels = series.map((p) => new Date(p[0] * 1000).toLocaleTimeString());
    chart.data.datasets[0].data = series.map((p) => p[1]);
    chart.update("none");
  }

  function destroyCharts() {
    [predictionsChart, latencyChart, driftScoreChart, confidenceChart].forEach((c) => {
      if (c) c.destroy();
    });
    predictionsChart = null;
    latencyChart = null;
    driftScoreChart = null;
    confidenceChart = null;
  }

  function ensureCharts() {
    if (!predictionsChart) predictionsChart = makeLineChart("chart-predictions", "#2563eb");
    if (!latencyChart) latencyChart = makeLineChart("chart-latency", "#7c3aed");
    if (!driftScoreChart) driftScoreChart = makeDriftScoreChart("chart-driftscore");
    // model-runner/custom-runner set prediction_confidence (see their
    // main.py); model-service predates that instrumentation and doesn't
    // export it, so this chart just stays empty with a "no data" meta
    // readout for that one job — same makeLineChart shape (value +
    // baseline) as predictions/latency, since a typical-confidence
    // baseline is exactly what makes a confidence *drop* visible.
    if (!confidenceChart) confidenceChart = makeLineChart("chart-confidence", "#059669");
  }

  function chartPanelHtml(canvasId, title, metaId, color, legendLabel, withBaseline) {
    const legend =
      '<div class="chart-legend-note"><span><span class="legend-swatch" style="color:' + color + ';background:' + color + '"></span>' + legendLabel + "</span>" +
      (withBaseline ? '<span><span class="legend-swatch is-dashed" style="color:#8a8a9a"></span>baseline</span>' : "") +
      "</div>";
    // Label above (small, uppercase, muted), chart, then the current
    // value below it — not a title+value pair on one header row.
    return (
      '<div class="chart-panel-compact evidence-panel">' +
      '<div class="chart-panel-label">' + title + '</div>' +
      '<div class="chart-canvas-wrap"><canvas id="' + canvasId + '"></canvas></div>' +
      '<div class="chart-panel-value" id="' + metaId + '">&mdash;</div>' +
      legend +
      "</div>"
    );
  }

  function perfGridHtml() {
    return (
      '<div class="metric-grid" style="margin-bottom:var(--space-5)">' +
      chartPanelHtml("chart-predictions", "Predictions", "perf-rate-val", "#2563eb", "predictions/min", true) +
      chartPanelHtml("chart-latency", "Latency (p95)", "perf-latency-val", "#7c3aed", "p95, 5min window", true) +
      chartPanelHtml("chart-driftscore", "Drift score", "perf-drift-val", "#dc2626", "share of features drifted", false) +
      chartPanelHtml("chart-confidence", "Confidence", "perf-confidence-val", "#059669", "avg. prediction confidence", true) +
      "</div>"
    );
  }

  // Whether a model has performance data is a runtime fact (has anyone
  // actually called predict on it recently, and is Prometheus scraping
  // it), not something to hardcode per model kind — a model-runner/
  // custom-runner deployment is just as capable of reporting real
  // metrics as the core service once it's received traffic. This is
  // shown whenever the latest fetch came back empty, whoever the
  // selected model is, and clears itself on the next poll once data
  // shows up — no page reload needed.
  function noDataHtml() {
    // Spec: no bordered empty-state card here — just a quiet message.
    return '<p class="text-muted" style="font-size:var(--text-sm);margin-bottom:var(--space-5)">No telemetry data available yet — make some predictions and check back in 30 seconds.</p>';
  }

  function metricsHaveData(d) {
    return (
      d.predictions_total != null ||
      d.latency_p95 != null ||
      d.drift_score != null ||
      d.prediction_confidence != null ||
      (d.prediction_rate_history && d.prediction_rate_history.length > 0) ||
      (d.latency_p95_history && d.latency_p95_history.length > 0) ||
      (d.prediction_confidence_history && d.prediction_confidence_history.length > 0)
    );
  }

  async function loadCatalog() {
    const contentEl = document.getElementById("model-content");
    const emptyEl = document.getElementById("model-empty");
    try {
      entries = await ModelCatalog.load(role);
    } catch (e) {
      console.error("Monitoring: ModelCatalog.load failed", e);
      emptyEl.innerHTML = UI.errorState(e.message, loadCatalog);
      contentEl.hidden = true;
      return;
    }
    if (!entries.length) {
      emptyEl.innerHTML = UI.emptyState(
        "No models available",
        role === "admin" ? "No deployments exist yet." : "Your teams haven't been granted access to any models yet."
      );
      contentEl.hidden = true;
      document.getElementById("model-picker").innerHTML = "";
      return;
    }
    emptyEl.innerHTML = "";
    contentEl.hidden = false;
    selectedKey = ModelCatalog.pickDefault(entries, ModelCatalog.getSelected());
    ModelCatalog.renderPicker("model-picker", entries, selectedKey, onSelect);
    renderModel();
  }

  function onSelect(key) {
    selectedKey = key;
    ModelCatalog.setSelected(key);
    verdictState = { status: null, drifted: null, rate: null };
    renderModel();
  }

  function currentEntry() {
    return entries.find((e) => e.key === selectedKey);
  }

  async function loadHealth(entry) {
    const badgeEl = document.getElementById("mh-status-badge");
    const statsEl = document.getElementById("mh-status-stats");
    statsEl.innerHTML = '<span class="skeleton skeleton-text" style="width:160px;display:inline-block">&nbsp;</span>';
    try {
      if (entry.kind === "custom") {
        const s = await Api.get("/api/v1/custom-model-status/" + entry.deploymentId);
        const phase = (s && s.phase) || "unknown";
        badgeEl.innerHTML = UI.badge(customPhaseLabel(phase), customPhaseVariant(phase), true);
        statsEl.innerHTML = statLine(customPhaseLabel(phase), "Phase") + (s && s.detail ? statLine(s.detail, "Detail") : "");
        verdictState.status = phase === "running" ? "running" : phase === "failed" ? "failed" : "starting";
      } else {
        const deployments = await Api.get("/deployments");
        const d = deployments.find((x) => x.name === entry.deploymentName);
        const status = d ? d.status : entry.status || "unknown";
        badgeEl.innerHTML = UI.statusBadge(status);
        statsEl.innerHTML = statLine(d ? d.ready + "/" + d.desired : "—", "Replicas ready");
        verdictState.status = status;
      }
    } catch (e) {
      statsEl.innerHTML = UI.errorState(e.message);
      badgeEl.innerHTML = "";
      verdictState.status = null;
    }
    renderVerdict();
  }

  // One-line synthesis of health + drift + traffic (spec: "● Running
  // normally — no drift detected — 142 req/min" / "⚠ Drift detected —
  // confidence score dropped — investigate below"). Each piece updates
  // verdictState independently (loadHealth sets status, loadPerformance
  // sets drifted/rate) and re-renders through this shared function so
  // whichever one resolves last still produces a complete line.
  function renderVerdict() {
    const el = document.getElementById("mh-verdict");
    if (!el) return;
    const s = String(verdictState.status || "").toLowerCase();
    const isRunning = s === "online" || s === "running" || s === "healthy" || s === "active";
    const isKnown = s && s !== "unknown";
    if (verdictState.drifted) {
      el.innerHTML = "&#9888; Drift detected — investigate below.";
      return;
    }
    if (!isKnown) {
      el.textContent = "Status unknown for this model.";
      return;
    }
    const rateText = verdictState.rate == null ? "no traffic yet" : fmtN(verdictState.rate, 1) + " req/min";
    el.innerHTML =
      UI.statusDot(isRunning ? "Running normally" : "Needs attention", isRunning ? "running" : "warning") +
      ' <span class="text-secondary">— ' + (verdictState.drifted === false ? "no drift detected" : "drift status unknown") +
      " — " + rateText + "</span>";
  }

  function renderDriftTeaser(entry, metrics) {
    const el = document.getElementById("mh-drift-teaser");
    if (!metrics || metrics.drift_score == null) {
      el.innerHTML = '<span class="text-secondary" style="font-size:var(--text-sm)">No drift computation available for this model.</span>';
      verdictState.drifted = null;
      renderVerdict();
      return;
    }
    const pct = (metrics.drift_score * 100).toFixed(1) + "%";
    const columns = (metrics.drift_details && metrics.drift_details.columns) || [];
    const drifted = columns.some((c) => c.drifted);
    el.innerHTML =
      '<div style="display:flex;align-items:center;gap:var(--space-3)">' +
      UI.statusDot(drifted ? "Drift detected" : "Stable", drifted ? "warning" : "running") +
      '<span style="font-size:var(--text-sm)">' + pct + " of tracked features drifted</span></div>";
    verdictState.drifted = drifted;
    renderVerdict();
  }

  // job alone identifies model-service; every model-runner/custom-runner
  // deployment shares one job behind the platform-runner PodMonitor, so
  // `pod` (a regex matching that deployment's pod-name prefix — see
  // models.js) rides along whenever the model in question needs it.
  function jobParams(job, pod, deploymentId) {
    const params = new URLSearchParams({ job });
    if (pod) params.set("pod", pod);
    // Only /metrics-summary understands this (see services/
    // drift_tracker.py) — /timeline and /summary don't take it and
    // ignore it harmlessly on the rare call site that passes one anyway.
    if (deploymentId != null) params.set("deployment_id", deploymentId);
    return params.toString();
  }

  async function renderSummary(job, pod) {
    const box = document.getElementById("summary-box");
    if (!job) {
      box.textContent = "No telemetry to summarize for this model yet.";
      return;
    }
    try {
      const d = await Api.get("/summary?window_minutes=360&" + jobParams(job, pod));
      box.textContent = d.summary || "No summary.";
    } catch (e) {
      box.textContent = "Summary unavailable: " + e.message;
    }
  }

  async function renderTimeline(job, pod) {
    const statusEl = document.getElementById("timeline-status");
    const listEl = document.getElementById("timeline-list");
    if (!job) {
      statusEl.textContent = "";
      listEl.innerHTML = UI.emptyState("No events", "This model has no telemetry to derive events from.");
      return [];
    }
    try {
      const events = await Api.get("/timeline?window_minutes=360&" + jobParams(job, pod));
      statusEl.textContent = "— " + events.length + " events — last 6h — refreshes every 30s";
      if (!events.length) {
        listEl.innerHTML = UI.emptyState("No events in this window", "Deploys, drift samples and latency readings will show up here.");
      } else {
        listEl.innerHTML = events
          .slice()
          .reverse()
          .slice(0, 40)
          .map((e) => {
            const variant = e.type === "drift" ? "danger" : e.type === "latency_p95" ? "success" : "info";
            return (
              '<div class="event-row"><span class="event-time">' + new Date(e.timestamp * 1000).toLocaleString() + "</span>" +
              UI.badge(e.type, variant) + '<span class="text-secondary">' + UI.escapeHtml(e.detail) + "</span></div>"
            );
          })
          .join("");
      }
      return events;
    } catch (e) {
      statusEl.textContent = "Error loading events: " + e.message;
      return [];
    }
  }

  async function loadPerformance(entry) {
    const el = document.getElementById("mh-performance");

    // No job at all to query yet (a platform/custom deployment whose
    // Prometheus job isn't resolvable client-side) — same "no data"
    // state and message as a job that resolves but has nothing to
    // report, just without a fetch to make first.
    if (!entry.job) {
      const marker = "no-data:" + entry.key;
      if (performanceBuiltFor !== marker) {
        destroyCharts();
        el.innerHTML = noDataHtml();
        performanceBuiltFor = marker;
      }
      renderDriftTeaser(entry, null);
      await renderSummary(null);
      await renderTimeline(null);
      return;
    }

    let d, events;
    try {
      [d, events] = await Promise.all([
        Api.get("/metrics-summary?" + jobParams(entry.job, entry.pod, entry.deploymentId)),
        renderTimeline(entry.job, entry.pod),
      ]);
    } catch (e) {
      // Leave whatever's already on screen alone — replacing the grid's
      // innerHTML here would tear down the live charts on every failed
      // poll, which is the same bug the built-DOM-caching below exists
      // to avoid.
      console.error("Monitoring: loadPerformance refresh failed", e);
      UI.toast("Could not refresh metrics: " + e.message, "danger");
      return;
    }

    if (!metricsHaveData(d)) {
      const marker = "no-data:" + entry.key;
      if (performanceBuiltFor !== marker) {
        destroyCharts();
        el.innerHTML = noDataHtml();
        performanceBuiltFor = marker;
      }
      renderDriftTeaser(entry, d);
      await renderSummary(entry.job, entry.pod);
      return;
    }

    // Only rebuild the grid's DOM (and the Chart.js instances bound to
    // it) when the selected model changes, or when it just went from no
    // data to having some — NOT on every poll tick while nothing about
    // that has changed. A poll on an already-built grid just re-fetches
    // and calls setChartData()/setDriftScoreData() on the charts already
    // in place.
    if (performanceBuiltFor !== entry.key) {
      destroyCharts();
      el.innerHTML = perfGridHtml();
      ensureCharts();
      performanceBuiltFor = entry.key;
    }

    verdictState.rate = d.prediction_rate_5m;
    renderVerdict();

    const rateVal = d.prediction_rate_5m == null ? "no data" : fmtN(d.prediction_rate_5m, 1) + "/min";
    const latVal = d.latency_p95 == null ? "no data" : fmtN(d.latency_p95 * 1000, 0) + "ms";
    const driftVal = d.drift_score == null ? "no data" : (d.drift_score * 100).toFixed(1) + "%";
    const confVal = d.prediction_confidence == null ? "no data" : (d.prediction_confidence * 100).toFixed(1) + "%";
    const rateEl = document.getElementById("perf-rate-val");
    const latEl = document.getElementById("perf-latency-val");
    const driftEl = document.getElementById("perf-drift-val");
    const confEl = document.getElementById("perf-confidence-val");
    if (rateEl) rateEl.textContent = rateVal;
    if (latEl) latEl.textContent = latVal;
    if (driftEl) driftEl.textContent = driftVal;
    if (confEl) confEl.textContent = confVal;

    const deployTimestamps = (events || []).filter((e) => e.type === "deploy").map((e) => e.timestamp);
    setChartData(predictionsChart, d.prediction_rate_history || [], deployTimestamps);
    setChartData(latencyChart, d.latency_p95_history || [], deployTimestamps);
    setDriftScoreData(driftScoreChart, d.drift_history || []);
    setChartData(confidenceChart, d.prediction_confidence_history || [], deployTimestamps);
    renderDriftTeaser(entry, d);
    await renderSummary(entry.job, entry.pod);
  }

  async function renderModel() {
    const entry = currentEntry();
    if (!entry) return;
    document.getElementById("mh-name").textContent = entry.label;
    document.getElementById("mh-task").textContent = ModelCatalog.kindLabel(entry.kind) + (entry.task ? " · " + entry.task : "");
    document.getElementById("mh-drift-link").href = (role === "admin" ? "/admin/drift" : "/app/drift") + "?model=" + encodeURIComponent(entry.key);
    await Promise.all([loadHealth(entry), loadPerformance(entry)]);
  }

  function start(opts) {
    role = (opts && opts.role) || "member";
    loadCatalog();
    pollHandle = setInterval(() => {
      const entry = currentEntry();
      if (entry) renderModel();
    }, 30000);
  }

  function stop() {
    if (pollHandle) clearInterval(pollHandle);
  }

  return { start, stop };
})();
