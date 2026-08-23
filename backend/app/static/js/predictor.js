/*
 * Vela inline prediction tester — shared by /app/teams/{id} and
 * /app/models (member_pages.py). One tester per team+deployment pair:
 *
 *   const uid = 'd' + deployment_id;              // unique per page
 *   container.innerHTML = Predictor.render(uid, team_id, deployment_id);
 *   Predictor.wire(uid, team_id, deployment_id);   // after insertion
 *
 * The API key used to call /api/v1/predict is never routed through the
 * shared Api helper (that attaches the JWT and treats any 401 as
 * "session expired") — it's a workspace-scoped model key the member
 * pastes in once per team+model and it's kept in sessionStorage under
 * vela_key_{team_id}_{deployment_id}, not the JWT-backed session.
 */

const Predictor = (() => {
  function keyFor(teamId, deploymentId) {
    return "vela_key_" + teamId + "_" + deploymentId;
  }

  function getKey(teamId, deploymentId) {
    try {
      return sessionStorage.getItem(keyFor(teamId, deploymentId)) || "";
    } catch (e) {
      return "";
    }
  }

  function setKey(teamId, deploymentId, value) {
    try {
      sessionStorage.setItem(keyFor(teamId, deploymentId), value);
    } catch (e) {}
  }

  function clearKey(teamId, deploymentId) {
    try {
      sessionStorage.removeItem(keyFor(teamId, deploymentId));
    } catch (e) {}
  }

  /* ---- Markup ----------------------------------------------------------*/

  function keyPromptHtml(uid) {
    return (
      '<div class="field" style="margin-bottom:.4rem">' +
      '<label class="field-label" for="predict-key-' + uid + '">Enter your API key for this model:</label>' +
      '<div style="display:flex;gap:.4rem">' +
      '<input class="input" type="password" id="predict-key-' + uid + '" placeholder="aodp_…" style="font-size:var(--text-xs)">' +
      '<button class="btn btn-secondary btn-sm" data-save-key="' + uid + '" type="button" style="flex-shrink:0">Save</button>' +
      "</div>" +
      "</div>"
    );
  }

  function testerHtml(uid) {
    return (
      '<div class="field" style="margin-bottom:.4rem">' +
      '<textarea class="textarea" id="predict-input-' + uid + '" placeholder="Enter text to analyze…" style="font-size:var(--text-xs);min-height:3.5em"></textarea>' +
      "</div>" +
      '<button class="btn btn-secondary btn-sm" data-run="' + uid + '" type="button">Run prediction</button>' +
      '<div id="predict-result-' + uid + '" style="margin-top:.6rem"></div>' +
      '<a class="link-secondary" href="#" data-clear-key="' + uid + '" style="font-size:var(--text-xs);display:inline-block;margin-top:.5rem">Clear key</a>'
    );
  }

  // Full tester block for one team+deployment pair. `uid` must be unique
  // among every tester rendered on the same page (callers use
  // 'd' + deployment_id, which is unique per page in both call sites).
  function render(uid, teamId, deploymentId) {
    const hasKey = !!getKey(teamId, deploymentId);
    return (
      '<div class="predict-tester" id="predict-' + uid + '">' +
      (hasKey ? testerHtml(uid) : keyPromptHtml(uid)) +
      "</div>"
    );
  }

  /* ---- Wiring ------------------------------------------------------------*/

  // Attaches event listeners for one tester block — call once, right
  // after its render() output has been inserted into the DOM. Safe to
  // call again after the block's own innerHTML is swapped between the
  // key-prompt and tester states (only the elements that actually exist
  // in the current state are found and wired).
  function wire(uid, teamId, deploymentId) {
    const root = document.getElementById("predict-" + uid);
    if (!root) return;

    const saveBtn = root.querySelector('[data-save-key="' + uid + '"]');
    if (saveBtn) {
      const keyInput = document.getElementById("predict-key-" + uid);
      const save = () => {
        const value = (keyInput.value || "").trim();
        if (!value) return;
        setKey(teamId, deploymentId, value);
        root.innerHTML = testerHtml(uid);
        wire(uid, teamId, deploymentId);
      };
      saveBtn.addEventListener("click", save);
      keyInput.addEventListener("keydown", (e) => {
        if (e.key === "Enter") save();
      });
    }

    const runBtn = root.querySelector('[data-run="' + uid + '"]');
    if (runBtn) {
      runBtn.addEventListener("click", () => runPrediction(uid, teamId, deploymentId));
    }

    const clearLink = root.querySelector('[data-clear-key="' + uid + '"]');
    if (clearLink) {
      clearLink.addEventListener("click", (e) => {
        e.preventDefault();
        clearKey(teamId, deploymentId);
        root.innerHTML = keyPromptHtml(uid);
        wire(uid, teamId, deploymentId);
      });
    }
  }

  /* ---- Predicting --------------------------------------------------------*/

  function sentimentVariant(label) {
    const l = String(label || "").toLowerCase();
    if (l.indexOf("pos") !== -1) return "success";
    if (l.indexOf("neg") !== -1) return "danger";
    return "neutral"; // grey — neutral, or any label this app doesn't specifically color
  }

  function meterRow(label, pct) {
    return (
      '<div class="meter-label"><span>' + UI.escapeHtml(label) + "</span><span>" + pct + "%</span></div>" +
      '<div class="meter-track"><div class="meter-fill" style="width:' + pct + '%"></div></div>'
    );
  }

  function renderResult(result) {
    if (result.all_labels && Object.keys(result.all_labels).length) {
      // Zero-shot — ranked labels as a small bar chart.
      const ranked = Object.entries(result.all_labels).sort((a, b) => b[1] - a[1]);
      return ranked
        .map(([label, score]) => meterRow(label, Math.round(score * 1000) / 10))
        .join('<div style="height:.4rem"></div>');
    }
    if (result.label != null) {
      // Sentiment — colored label badge + confidence bar.
      const pct = result.score != null ? Math.round(result.score * 1000) / 10 : null;
      return (
        '<div style="margin-bottom:.4rem">' + UI.badge(result.label, sentimentVariant(result.label), true) + "</div>" +
        (pct != null ? meterRow("Confidence", pct) : "")
      );
    }
    return '<div class="text-muted" style="font-size:var(--text-xs)">No result returned.</div>';
  }

  async function runPrediction(uid, teamId, deploymentId) {
    const input = document.getElementById("predict-input-" + uid);
    const resultEl = document.getElementById("predict-result-" + uid);
    const btn = document.querySelector('[data-run="' + uid + '"]');
    const text = (input.value || "").trim();
    if (!text) {
      resultEl.innerHTML = '<div class="field-error" style="min-height:0">Enter some text first.</div>';
      return;
    }

    const apiKey = getKey(teamId, deploymentId);
    const originalLabel = btn.textContent;
    btn.disabled = true;
    btn.textContent = "Running…";
    resultEl.innerHTML = '<span class="skeleton skeleton-text" style="display:inline-block;width:50%">&nbsp;</span>';

    try {
      const res = await fetch("/api/v1/predict", {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-API-Key": apiKey },
        body: JSON.stringify({ text: text, deployment_id: deploymentId }),
      });
      const raw = await res.text();
      let data = null;
      if (raw) {
        try {
          data = JSON.parse(raw);
        } catch (e) {
          data = null;
        }
      }
      if (!res.ok) {
        if (res.status === 401) {
          // A stale/invalid key — drop back to the prompt instead of
          // leaving the member stuck retrying with a key that will
          // never work.
          clearKey(teamId, deploymentId);
          const root = document.getElementById("predict-" + uid);
          root.innerHTML =
            keyPromptHtml(uid) +
            '<div class="field-error">' + UI.escapeHtml((data && data.detail) || "Invalid API key.") + "</div>";
          wire(uid, teamId, deploymentId);
          return;
        }
        throw new Error((data && data.detail) || res.statusText || "Request failed");
      }
      resultEl.innerHTML = renderResult((data && data.result) || {});
    } catch (e) {
      resultEl.innerHTML = '<div class="field-error">' + UI.escapeHtml(e.message || "Request failed") + "</div>";
    } finally {
      btn.disabled = false;
      btn.textContent = originalLabel;
    }
  }

  return { render, wire, keyFor, getKey, setKey, clearKey };
})();
