/*
 * Vela drift analysis — shared by /admin/drift and /app/drift (spec §13/§14).
 *
 * Wired to GET /metrics-summary (its drift_details field carries the
 * per-column breakdown from the model service's Evidently report — see
 * model-service/main.py:compute_drift()) and GET /summary for the LLM
 * narrative.
 *
 * A few fields spec §13 asks for don't exist in the backend and are NOT
 * fabricated here:
 *   - "Change" (e.g. "+31%") per signal — Evidently's DataDriftPreset
 *     output only carries p_value/drifted/method per column, no magnitude.
 *     The breakdown table below has no Change column as a result.
 *   - A configurable "threshold" for the overall score — the only real
 *     threshold in this codebase is the per-column significance level
 *     hardcoded in model-service (p < 0.05), which is what's shown.
 *   - "Detection status" isn't a stored field — it's derived here from
 *     whether any column's real `drifted` flag is true.
 */

const Drift = (() => {
  function fmtPct(x) {
    return x == null || isNaN(x) ? "—" : (x * 100).toFixed(1) + "%";
  }

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

  function renderOverview(details, liveDriftScore) {
    const columns = (details && details.columns) || [];
    const share = details && typeof details.drift_share === "number" ? details.drift_share : liveDriftScore;

    document.getElementById("drift-score-value").textContent = fmtPct(share);
    document.getElementById("drift-score-raw").textContent = share == null ? "—" : Number(share).toFixed(4);

    const statusEl = document.getElementById("detection-status");
    if (!columns.length) {
      statusEl.innerHTML = UI.badge("No data yet", "neutral", true);
    } else if (columns.some((c) => c.drifted)) {
      statusEl.innerHTML = UI.badge("Drift detected", "danger", true);
    } else {
      statusEl.innerHTML = UI.badge("Stable", "success", true);
    }

    document.getElementById("detection-threshold").textContent = "p < 0.05 per signal";

    const methods = Array.from(new Set(columns.map((c) => c.method).filter(Boolean)));
    document.getElementById("statistical-test").textContent = methods.length ? methods.join(", ") : "—";

    document.getElementById("time-detected").textContent =
      details && details.computed_at ? fmtEpoch(details.computed_at) + " (" + timeAgoEpoch(details.computed_at) + ")" : "No computation yet";
  }

  function renderBreakdown(columns) {
    const body = document.getElementById("breakdown-body");
    if (!columns.length) {
      body.innerHTML =
        '<tr><td colspan="4">' +
        UI.emptyState("No drift computation yet", "Once enough prediction traffic has been observed, per-signal drift results will appear here.") +
        "</td></tr>";
      return;
    }
    body.innerHTML = columns
      .map(
        (c) =>
          "<tr><td>" + UI.escapeHtml(c.column) + "</td><td>" + UI.badge(c.method || "unknown", "neutral") + "</td><td>" + c.p_value +
          "</td><td>" + UI.badge(c.drifted ? "Drifted" : "Stable", c.drifted ? "danger" : "success") + "</td></tr>"
      )
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
      el.innerHTML = '<li class="text-secondary">All tracked signals are stable — nothing has drifted.</li>';
      return;
    }
    el.innerHTML = drifted
      .map(
        (c) =>
          "<li>" + UI.escapeHtml(c.column) + ' distribution has shifted <span class="text-muted">(p=' + c.p_value + ", " + UI.escapeHtml(c.method || "unknown") + " test)</span></li>"
      )
      .join("");
  }

  function renderRecommended(columns, opts) {
    const el = document.getElementById("recommended-list");
    const items = [];
    if (columns.some((c) => c.drifted)) {
      items.push("Review the drifted signals in the breakdown below to understand what shifted.");
      items.push("Check whether prediction confidence or latency have also moved, on the Model Health page.");
      items.push("If this needs follow-up, use the action below.");
    } else if (columns.length) {
      items.push("No drift detected in the current window — no action needed right now.");
    } else {
      items.push("Not enough traffic has been observed yet to compute drift.");
    }
    el.innerHTML = items.map((i) => "<li>" + i + "</li>").join("");

    const btn = document.getElementById("action-btn");
    if (btn && opts.actionHref) {
      btn.href = opts.actionHref;
      btn.textContent = opts.actionLabel || "Open";
    } else if (btn) {
      btn.style.display = "none";
    }
  }

  async function loadAiAnalysis() {
    const box = document.getElementById("ai-analysis-box");
    try {
      const d = await Api.get("/summary?window_minutes=360");
      box.textContent = d.summary || "No summary available for the current window.";
    } catch (e) {
      box.textContent = "AI analysis unavailable: " + e.message;
    }
  }

  async function load(opts) {
    try {
      const metrics = await Api.get("/metrics-summary");
      const details = metrics.drift_details || { drift_share: 0, columns: [], computed_at: null };
      const columns = details.columns || [];
      renderOverview(details, metrics.drift_score);
      renderBreakdown(columns);
      renderWhatChanged(columns);
      renderRecommended(columns, opts || {});
    } catch (e) {
      UI.toast("Could not load drift data: " + e.message, "danger");
    }
    loadAiAnalysis();
  }

  function start(opts) {
    load(opts || {});
  }

  return { start };
})();
