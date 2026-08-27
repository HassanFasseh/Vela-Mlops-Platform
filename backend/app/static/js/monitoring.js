/*
 * Vela Model Health — model-centric (spec redesign). Shared by
 * /admin/monitoring and /app/monitoring via Monitoring.start({role}).
 *
 * Selection comes from ModelCatalog (models.js); a model is either
 * `instrumented` (today: only the id=1 core service, job="model-service"
 * — see services/timeline.py DEFAULT_JOB) or it isn't, in which case the
 * Performance section says so honestly instead of drawing an empty/fake
 * chart. See drift.js for the linked full drift analysis.
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
        animation: false,
        plugins: { legend: { display: false } },
        scales: {
          x: { display: false },
          y: { beginAtZero: true, ticks: { font: { size: 10 } }, grid: { color: "rgba(128,128,128,0.12)" } },
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

  function ensureCharts() {
    if (!predictionsChart) predictionsChart = makeLineChart("chart-predictions", "#7eb8f7");
    if (!latencyChart) latencyChart = makeLineChart("chart-latency", "#38bdf8");
  }

  function perfPanelsHtml() {
    return (
      '<div class="evidence-panel" style="margin-bottom:var(--space-4)">' +
      '<div class="chart-panel-head"><div class="chart-panel-title">Predictions</div><div class="chart-panel-meta" id="perf-rate-val">&mdash;</div></div>' +
      '<canvas id="chart-predictions" height="70"></canvas>' +
      '<div class="chart-legend-note"><span><span class="legend-swatch" style="color:#7eb8f7;background:#7eb8f7"></span>predictions/min</span>' +
      '<span><span class="legend-swatch is-dashed" style="color:#8a8a9a"></span>baseline (window median)</span>' +
      '<span><span class="legend-swatch is-dashed" style="color:#8a8a9a"></span>vertical line = deploy event</span></div>' +
      '</div>' +
      '<div class="evidence-panel" style="margin-bottom:var(--space-4)">' +
      '<div class="chart-panel-head"><div class="chart-panel-title">Latency (p95)</div><div class="chart-panel-meta" id="perf-latency-val">&mdash;</div></div>' +
      '<canvas id="chart-latency" height="70"></canvas>' +
      '<div class="chart-legend-note"><span><span class="legend-swatch" style="color:#38bdf8;background:#38bdf8"></span>p95, 5min rolling window</span>' +
      '<span><span class="legend-swatch is-dashed" style="color:#8a8a9a"></span>baseline (window median)</span></div>' +
      "</div>"
    );
  }

  function notInstrumentedHtml(entry) {
    const why =
      entry.kind === "core"
        ? "This core service isn't scraped by Prometheus yet (only the primary sentiment service is)."
        : "Deployments outside the two core services aren't wired up to Prometheus yet — this is a platform instrumentation gap, not specific to this model.";
    return (
      '<div class="evidence-panel" style="margin-bottom:var(--space-5)">' +
      '<div class="not-instrumented"><div class="not-instrumented-title">No performance telemetry for this model</div><div>' +
      why + "</div></div></div>"
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
      if (entry.kind === "core") {
        const models = await Api.get("/models/status");
        const id = parseInt(entry.key.split(":")[1], 10);
        const m = models.find((x) => x.id === id);
        badgeEl.innerHTML = UI.statusBadge(m ? m.status : "unknown");
        statsEl.innerHTML =
          statLine(m && m.model !== "unavailable" ? m.model : "—", "Backing model") +
          statLine(entry.instrumented ? "Yes" : "No", "Instrumented");
      } else if (entry.kind === "custom") {
        const s = await Api.get("/api/v1/custom-model-status/" + entry.deploymentId);
        const phase = (s && s.phase) || "unknown";
        badgeEl.innerHTML = UI.badge(customPhaseLabel(phase), customPhaseVariant(phase), true);
        statsEl.innerHTML = statLine(customPhaseLabel(phase), "Phase") + (s && s.detail ? statLine(s.detail, "Detail") : "");
      } else {
        const deployments = await Api.get("/deployments");
        const d = deployments.find((x) => x.name === entry.deploymentName);
        badgeEl.innerHTML = UI.statusBadge(d ? d.status : entry.status || "unknown");
        statsEl.innerHTML = statLine(d ? d.ready + "/" + d.desired : "—", "Replicas ready");
      }
    } catch (e) {
      statsEl.innerHTML = UI.errorState(e.message);
      badgeEl.innerHTML = "";
    }
  }

  function renderDriftTeaser(entry, metrics) {
    const el = document.getElementById("mh-drift-teaser");
    if (!metrics || metrics.drift_score == null) {
      el.innerHTML = '<span class="text-secondary" style="font-size:var(--text-sm)">No drift computation available for this model.</span>';
      return;
    }
    const pct = (metrics.drift_score * 100).toFixed(1) + "%";
    const columns = (metrics.drift_details && metrics.drift_details.columns) || [];
    const drifted = columns.some((c) => c.drifted);
    el.innerHTML =
      '<div style="display:flex;align-items:center;gap:var(--space-3)">' +
      UI.badge(drifted ? "Drift detected" : "Stable", drifted ? "warning" : "success", true) +
      '<span style="font-size:var(--text-sm)">' + pct + " of tracked features drifted</span></div>";
  }

  async function renderSummary(job) {
    const box = document.getElementById("summary-box");
    if (!job) {
      box.textContent = "No telemetry to summarize for this model yet.";
      return;
    }
    try {
      const d = await Api.get("/summary?window_minutes=360&job=" + encodeURIComponent(job));
      box.textContent = d.summary || "No summary.";
    } catch (e) {
      box.textContent = "Summary unavailable: " + e.message;
    }
  }

  async function renderTimeline(job) {
    const statusEl = document.getElementById("timeline-status");
    const listEl = document.getElementById("timeline-list");
    if (!job) {
      statusEl.textContent = "";
      listEl.innerHTML = UI.emptyState("No events", "This model has no telemetry to derive events from.");
      return [];
    }
    try {
      const events = await Api.get("/timeline?window_minutes=360&job=" + encodeURIComponent(job));
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
    if (!entry.instrumented) {
      el.innerHTML = notInstrumentedHtml(entry);
      renderDriftTeaser(entry, null);
      await renderSummary(null);
      await renderTimeline(null);
      return;
    }
    el.innerHTML = perfPanelsHtml();
    ensureCharts();
    try {
      const [d, events] = await Promise.all([
        Api.get("/metrics-summary?job=" + encodeURIComponent(entry.job)),
        renderTimeline(entry.job),
      ]);
      const rateVal = d.prediction_rate_5m == null ? "no data" : fmtN(d.prediction_rate_5m, 1) + "/min (5m avg)";
      const latVal = d.latency_p95 == null ? "no data" : fmtN(d.latency_p95 * 1000, 0) + "ms (p95, 5m)";
      document.getElementById("perf-rate-val").textContent = rateVal;
      document.getElementById("perf-latency-val").textContent = latVal;
      const deployTimestamps = (events || []).filter((e) => e.type === "deploy").map((e) => e.timestamp);
      setChartData(predictionsChart, d.prediction_rate_history || [], deployTimestamps);
      setChartData(latencyChart, d.latency_p95_history || [], deployTimestamps);
      renderDriftTeaser(entry, d);
      await renderSummary(entry.job);
    } catch (e) {
      el.innerHTML = UI.errorState(e.message);
    }
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
