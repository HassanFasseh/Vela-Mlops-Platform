/*
 * Vela monitoring data layer — shared by /admin/monitoring and
 * /app/monitoring. Ported from /dashboard's loadMetrics/loadModels/
 * loadSummary/loadTimeline (same endpoints, same 30s polling cadence),
 * re-rendered through the shared design system instead of /dashboard's
 * one-off inline styles.
 *
 * Requires Chart.js (loaded via CDN, same as /dashboard) and ui.js.
 * Expects these elements to exist in the page:
 *   #m-rate #m-latency #m-drift #m-total
 *   #cpu-fill #cpu-val #mem-fill #mem-val
 *   #drift-chart (canvas) #latency-chart (canvas)
 *   #drift-details-wrap #drift-details-content
 *   #model-status-grid
 *   #summary-box
 *   #timeline-status #timeline-list
 */

const Monitoring = (() => {
  const WINDOW_MINUTES = 360;
  let driftChart = null;
  let latencyChart = null;
  let pollHandle = null;

  function fmtN(n, dec = 1) {
    return n == null || isNaN(n) ? "—" : Number(n).toFixed(dec);
  }

  function initCharts() {
    const driftCtx = document.getElementById("drift-chart");
    if (driftCtx && window.Chart) {
      driftChart = new Chart(driftCtx.getContext("2d"), {
        type: "line",
        data: { labels: [], datasets: [{ label: "Drift", data: [], borderColor: "#f77e7e", backgroundColor: "rgba(247,126,126,0.08)", borderWidth: 1.5, pointRadius: 0, fill: true, tension: 0.3 }] },
        options: {
          responsive: true,
          plugins: { legend: { display: false } },
          scales: {
            x: { display: false },
            y: { min: 0, max: 1, ticks: { color: "#8a8a9a", font: { size: 10 } }, grid: { color: "#1e1e2e" } },
          },
        },
      });
    }
    const latencyCtx = document.getElementById("latency-chart");
    if (latencyCtx && window.Chart) {
      latencyChart = new Chart(latencyCtx.getContext("2d"), {
        type: "line",
        data: { labels: [], datasets: [{ label: "p95 latency (ms)", data: [], borderColor: "#7eb8f7", backgroundColor: "rgba(126,184,247,0.08)", borderWidth: 1.5, pointRadius: 0, fill: true, tension: 0.3 }] },
        options: {
          responsive: true,
          plugins: { legend: { display: false } },
          scales: {
            x: { display: false },
            y: { beginAtZero: true, ticks: { color: "#8a8a9a", font: { size: 10 } }, grid: { color: "#1e1e2e" } },
          },
        },
      });
    }
  }

  async function loadMetrics() {
    try {
      const d = await Api.get("/metrics-summary");
      setText("m-rate", fmtN(d.prediction_rate_5m, 1));
      setText("m-latency", d.latency_p95 > 0 ? fmtN(d.latency_p95 * 1000, 0) : "—");
      setText("m-drift", fmtN(d.drift_score, 3));
      setText("m-total", Math.round(d.predictions_total) || "—");

      const cpu = Math.round(d.node_cpu_percent || 0);
      const mu = d.node_memory_used_gb || 0;
      const mt = d.node_memory_total_gb || 0;
      const mp = mt > 0 ? Math.round((mu / mt) * 100) : 0;

      setMeter("cpu", cpu, cpu + "%");
      setMeter("mem", mp, fmtN(mu, 1) + "GB / " + fmtN(mt, 1) + "GB (" + mp + "%)");

      if (driftChart && d.drift_history && d.drift_history.length) {
        driftChart.data.labels = d.drift_history.map((p) => new Date(p[0] * 1000).toLocaleTimeString());
        driftChart.data.datasets[0].data = d.drift_history.map((p) => p[1]);
        driftChart.update("none");
      }

      renderDriftDetails(d.drift_details);
    } catch (e) {
      UI.toast("Could not load metrics: " + e.message, "danger");
    }
  }

  function setText(id, value) {
    const el = document.getElementById(id);
    if (el) el.textContent = value;
  }

  function setMeter(prefix, pct, label) {
    const fill = document.getElementById(prefix + "-fill");
    const val = document.getElementById(prefix + "-val");
    if (fill) {
      fill.style.width = Math.min(100, Math.max(0, pct)) + "%";
      fill.className = "meter-fill" + (pct > 85 ? " is-danger" : pct > 65 ? " is-warning" : "");
    }
    if (val) val.textContent = label;
  }

  function renderDriftDetails(details) {
    const wrap = document.getElementById("drift-details-wrap");
    const content = document.getElementById("drift-details-content");
    if (!wrap || !content) return;
    if (!details || !details.columns || !details.columns.length) {
      wrap.hidden = true;
      return;
    }
    wrap.hidden = false;
    content.innerHTML = details.columns
      .map((c) => {
        const variant = c.drifted ? "danger" : "success";
        const pct = Math.round((1 - c.p_value) * 100);
        return (
          '<div style="display:flex;align-items:center;gap:.6rem;margin:.4rem 0;font-size:var(--text-sm)">' +
          '<span style="min-width:120px;color:var(--color-text)">' + UI.escapeHtml(c.column) + "</span>" +
          '<div class="meter-track" style="flex:1;margin:0"><div class="meter-fill' + (c.drifted ? " is-danger" : "") + '" style="width:' + pct + '%"></div></div>' +
          '<span style="min-width:110px;text-align:right">' + UI.badge(c.drifted ? "Drifted" : "Stable", variant) + ' <span class="text-muted">p=' + c.p_value + "</span></span>" +
          "</div>"
        );
      })
      .join("");
  }

  async function loadTimelineAndLatencyChart() {
    const statusEl = document.getElementById("timeline-status");
    const listEl = document.getElementById("timeline-list");
    try {
      const events = await Api.get("/timeline?window_minutes=" + WINDOW_MINUTES);
      if (statusEl) statusEl.textContent = "— " + events.length + " events — last " + WINDOW_MINUTES + "min — refreshes every 30s";
      if (listEl) {
        if (!events.length) {
          listEl.innerHTML = UI.emptyState("No events in this window", "Deploys, drift samples and latency readings will show up here.");
        } else {
          listEl.innerHTML = events
            .slice()
            .reverse()
            .map((e) => {
              const variant = e.type === "drift" ? "danger" : e.type === "latency_p95" ? "success" : "info";
              return (
                '<li style="display:flex;gap:.6rem;align-items:baseline;padding:.3rem 0;border-bottom:1px solid var(--color-border-subtle);font-size:var(--text-sm)">' +
                '<span class="text-muted" style="min-width:150px;flex-shrink:0;font-size:var(--text-xs)">' + new Date(e.timestamp * 1000).toLocaleString() + "</span>" +
                UI.badge(e.type, variant) +
                '<span class="text-secondary">' + UI.escapeHtml(e.detail) + "</span>" +
                "</li>"
              );
            })
            .join("");
        }
      }

      if (latencyChart) {
        const latencyEvents = events.filter((e) => e.type === "latency_p95");
        latencyChart.data.labels = latencyEvents.map((e) => new Date(e.timestamp * 1000).toLocaleTimeString());
        latencyChart.data.datasets[0].data = latencyEvents.map((e) => parseFloat(e.detail));
        latencyChart.update("none");
      }
    } catch (e) {
      if (statusEl) statusEl.textContent = "Error loading timeline: " + e.message;
    }
  }

  async function loadSummary() {
    const box = document.getElementById("summary-box");
    if (!box) return;
    try {
      const d = await Api.get("/summary?window_minutes=" + WINDOW_MINUTES);
      box.textContent = d.summary || "No summary.";
    } catch (e) {
      box.textContent = "Summary unavailable: " + e.message;
    }
  }

  async function loadModelStatus() {
    const grid = document.getElementById("model-status-grid");
    if (!grid) return;
    try {
      const [models, deployments] = await Promise.all([Api.get("/models/status"), Api.get("/deployments")]);
      const rows = [];
      models.forEach((m) => rows.push({ name: m.name, task: m.task, source: "Core service", status: m.status, detail: "backing model: " + (m.model || "unknown") }));
      deployments.forEach((d) => rows.push({ name: d.name, task: d.task_type, source: "Deployment", status: d.status, detail: d.ready + "/" + d.desired + " replicas ready" }));
      if (!rows.length) {
        grid.innerHTML = UI.emptyState("No models deployed yet", "Infrastructure status will appear here once models are deployed.");
        return;
      }
      grid.innerHTML = rows
        .map(
          (r) =>
            '<div class="card"><div class="card-title">' + UI.escapeHtml(r.name) + "</div>" +
            '<div class="card-subtitle">' + UI.escapeHtml(r.task) + " &middot; " + UI.escapeHtml(r.source) + "</div>" +
            '<div style="margin:.5rem 0">' + UI.statusBadge(r.status) + "</div>" +
            '<div class="text-secondary" style="font-size:var(--text-xs)">' + UI.escapeHtml(r.detail) + "</div></div>"
        )
        .join("");
    } catch (e) {
      grid.innerHTML = UI.errorState(e.message);
    }
  }

  async function load() {
    await Promise.all([loadMetrics(), loadModelStatus(), loadSummary(), loadTimelineAndLatencyChart()]);
  }

  function start() {
    initCharts();
    load();
    pollHandle = setInterval(load, 30000);
  }

  function stop() {
    if (pollHandle) clearInterval(pollHandle);
  }

  return { start, stop, load };
})();
