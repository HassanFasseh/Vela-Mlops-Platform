/*
 * Vela Drift — model-centric, the standout page (spec goal #5). Shared by
 * /admin/drift and /app/drift via Drift.start({role, actionHrefFor, actionLabel}).
 *
 * There is exactly one drift pipeline in this backend (model-service's
 * Evidently DataDriftPreset, recomputed every 30 predictions against a
 * 30-sample reference window — see model-service/main.py) — selecting any
 * other model here shows an honest "not instrumented" state instead of a
 * fabricated chart. A few fields a fuller spec might want don't exist in
 * the backend and are NOT invented:
 *   - "Change" (e.g. "+31%") per feature — Evidently's output only carries
 *     p_value/drifted/method per column, no magnitude/delta.
 *   - A configurable overall-score threshold — the only real threshold is
 *     the per-feature significance level hardcoded in model-service
 *     (p < 0.05), which is what's shown. (RemediationConfig.drift_threshold
 *     exists for real Deployment rows, but the one model that actually has
 *     a drift signal today, the core sentiment service, isn't a Deployment
 *     row and can never have one — so it's not wired in here.)
 *
 * Expects in the page: #model-picker #model-empty #d-name #d-task
 *   #d-status-badge #d-not-instrumented #d-instrumented #d-share
 *   #d-computed #d-since #drift-chart #breakdown-list #ai-analysis-box
 *   #what-changed-list #recommended-list #action-btn
 */

const Drift = (() => {
  let role = "member";
  let entries = [];
  let selectedKey = null;
  let opts = {};
  let driftChart = null;

  function fmtEpoch(sec) {
    if (!sec) return "—";
    return new Date(sec * 1000).toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
  }

  function timeAgoEpoch(sec) {
    if (!sec) return "—";
    const seconds = Math.max(0, Date.now() / 1000 - sec);
    if (seconds < 60) return "just now";
    const mins = Math.floor(seconds / 60);
    if (mins < 60) return mins + "m ago";
    const hours = Math.floor(mins / 60);
    if (hours < 24) return hours + "h ago";
    return fmtEpoch(sec);
  }

  /* First timestamp of the current unbroken run of nonzero drift-share
     readings, scanning backward from the most recent point — i.e. "since
     when has drift been continuously present", derived purely from the
     history Prometheus actually returned, not a stored "detected_at". */
  function driftSince(history) {
    if (!history || !history.length) return null;
    let i = history.length - 1;
    if (!(history[i][1] > 0)) return null;
    while (i > 0 && history[i - 1][1] > 0) i--;
    return history[i][0];
  }

  function ensureChart() {
    const ctx = document.getElementById("drift-chart");
    if (!ctx || !window.Chart || driftChart) return;
    driftChart = new Chart(ctx.getContext("2d"), {
      type: "line",
      data: { labels: [], datasets: [{ label: "Drift share", data: [], borderColor: "#f77e7e", backgroundColor: "rgba(247,126,126,0.08)", borderWidth: 1.5, pointRadius: 0, fill: true, tension: 0.25 }] },
      options: {
        responsive: true,
        animation: false,
        plugins: { legend: { display: false } },
        scales: {
          x: { display: false },
          y: { min: 0, max: 1, ticks: { font: { size: 10 } }, grid: { color: "rgba(128,128,128,0.12)" } },
        },
      },
    });
  }

  function setChartData(history) {
    if (!driftChart) return;
    driftChart.data.labels = history.map((p) => new Date(p[0] * 1000).toLocaleTimeString());
    driftChart.data.datasets[0].data = history.map((p) => p[1]);
    driftChart.update("none");
  }

  function renderBreakdown(columns) {
    const el = document.getElementById("breakdown-list");
    if (!columns.length) {
      el.innerHTML = UI.emptyState("No drift computation yet", "Once enough prediction traffic has been observed, per-feature drift results will appear here.");
      return;
    }
    el.innerHTML = columns
      .map((c) => {
        const magnitude = Math.round((1 - c.p_value) * 100);
        return (
          '<div class="feature-row">' +
          '<div class="feature-name">' + UI.escapeHtml(c.column) + "</div>" +
          '<div class="feature-bar-track"><div class="feature-bar-fill' + (c.drifted ? " is-drifted" : "") + '" style="width:' + magnitude + '%"></div></div>' +
          '<div class="feature-meta">' + UI.badge(c.drifted ? "Drifted" : "Stable", c.drifted ? "danger" : "success") +
          "<span>p=" + c.p_value + "</span><span>" + UI.escapeHtml(c.method || "unknown") + " test</span></div>" +
          "</div>"
        );
      })
      .join("");
  }

  function renderWhatChanged(columns) {
    const el = document.getElementById("what-changed-list");
    if (!columns.length) {
      el.innerHTML = '<li class="text-secondary">No drift computation yet — nothing to compare.</li>';
      return;
    }
    const drifted = columns.filter((c) => c.drifted);
    if (!drifted.length) {
      el.innerHTML = '<li class="text-secondary">All tracked features are stable — nothing has drifted.</li>';
      return;
    }
    el.innerHTML = drifted
      .map((c) => "<li>" + UI.escapeHtml(c.column) + ' distribution has shifted <span class="text-muted">(p=' + c.p_value + ", " + UI.escapeHtml(c.method || "unknown") + " test)</span></li>")
      .join("");
  }

  function renderRecommended(columns) {
    const el = document.getElementById("recommended-list");
    const items = [];
    if (columns.some((c) => c.drifted)) {
      items.push("Review the drifted features in the breakdown above to understand what shifted.");
      items.push("Check whether latency or prediction volume have also moved, on Model Health.");
      items.push("If this needs follow-up, use the action below.");
    } else if (columns.length) {
      items.push("No drift detected in the current window — no action needed right now.");
    } else {
      items.push("Not enough traffic has been observed yet to compute drift.");
    }
    el.innerHTML = items.map((i) => "<li>" + i + "</li>").join("");

    const btn = document.getElementById("action-btn");
    const entry = currentEntry();
    if (btn && opts.actionHrefFor) {
      btn.href = opts.actionHrefFor(entry);
      btn.textContent = opts.actionLabel || "Open";
      btn.style.display = "";
    } else if (btn) {
      btn.style.display = "none";
    }
  }

  async function loadAiAnalysis(job) {
    const box = document.getElementById("ai-analysis-box");
    if (!job) {
      box.textContent = "No telemetry to explain for this model yet.";
      return;
    }
    try {
      const d = await Api.get("/summary?window_minutes=360&job=" + encodeURIComponent(job));
      box.textContent = d.summary || "No summary available for the current window.";
    } catch (e) {
      box.textContent = "AI analysis unavailable: " + e.message;
    }
  }

  function renderNotInstrumented(entry) {
    document.getElementById("d-instrumented").hidden = true;
    const why =
      entry.kind === "core"
        ? "This core service isn't wired up to the drift pipeline (only the primary sentiment service is)."
        : "Drift detection only runs for the platform's primary sentiment service today — this model isn't instrumented for it.";
    document.getElementById("d-not-instrumented").innerHTML =
      '<div class="evidence-panel"><div class="not-instrumented"><div class="not-instrumented-title">No drift detection for this model</div><div>' + why + "</div></div></div>";
  }

  async function renderModel() {
    const entry = currentEntry();
    if (!entry) return;
    document.getElementById("d-name").textContent = entry.label;
    document.getElementById("d-task").textContent = ModelCatalog.kindLabel(entry.kind) + (entry.task ? " · " + entry.task : "");
    document.getElementById("d-status-badge").innerHTML = "";
    document.getElementById("d-not-instrumented").innerHTML = "";

    if (!entry.instrumented) {
      renderNotInstrumented(entry);
      return;
    }

    document.getElementById("d-instrumented").hidden = false;
    ensureChart();
    try {
      const metrics = await Api.get("/metrics-summary?job=" + encodeURIComponent(entry.job));
      const details = metrics.drift_details || { drift_share: null, columns: [], computed_at: null };
      const columns = details.columns || [];
      const share = metrics.drift_score;

      document.getElementById("d-status-badge").innerHTML = !columns.length
        ? UI.badge("No data yet", "neutral", true)
        : columns.some((c) => c.drifted)
        ? UI.badge("Drift detected", "warning", true)
        : UI.badge("Stable", "success", true);

      document.getElementById("d-share").textContent = share == null ? "—" : (share * 100).toFixed(1) + "%";
      document.getElementById("d-computed").textContent = details.computed_at ? fmtEpoch(details.computed_at) + " (" + timeAgoEpoch(details.computed_at) + ")" : "No computation yet";

      const history = metrics.drift_history || [];
      const since = driftSince(history);
      document.getElementById("d-since").textContent = since
        ? "Continuously elevated since " + fmtEpoch(since) + " (" + timeAgoEpoch(since) + ")"
        : columns.some((c) => c.drifted)
        ? "Currently elevated — not enough history yet to say since when."
        : "No drift currently present in this window.";

      setChartData(history);
      renderBreakdown(columns);
      renderWhatChanged(columns);
      renderRecommended(columns);
      await loadAiAnalysis(entry.job);
    } catch (e) {
      UI.toast("Could not load drift data: " + e.message, "danger");
    }
  }

  async function loadCatalog() {
    const emptyEl = document.getElementById("model-empty");
    const contentEl = document.getElementById("drift-content");
    try {
      entries = await ModelCatalog.load(role);
    } catch (e) {
      console.error("Drift: ModelCatalog.load failed", e);
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

  function start(o) {
    opts = o || {};
    role = opts.role || "member";
    loadCatalog();
  }

  return { start };
})();
