/*
 * Vela inline prediction tester — shared by /app/teams/{id} and
 * /app/models (member_pages.py). One tester per team+deployment pair:
 *
 *   const uid = 'd' + deployment_id;              // unique per page
 *   container.innerHTML = Predictor.render(uid, team_id, deployment_id, input_type, input_schema);
 *   Predictor.wire(uid, team_id, deployment_id, input_type, input_schema);   // after insertion
 *
 * input_type/input_schema come straight off the permission row (GET
 * /teams/{id}/permissions — see services/teams.py's get_team_permissions)
 * and decide what the tester actually renders/sends:
 *   "text" (default, also used for "file" — no dedicated UI for that
 *           yet) — a plain textarea, {"text": ...}.
 *   "json" — input_schema is a JSON string like {"f1":"number"} stored
 *           on the deployment; parsed into one input field per key. No
 *           usable schema (missing/unparseable/empty) falls back to a
 *           raw-JSON textarea instead of losing the ability to predict
 *           entirely. Either way, sent as {"data": {...}}.
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

  // One <input> per input_schema key, e.g. {"age":"number","note":"string"}
  // -> an age number-input and a note text-input. Falls back to a single
  // raw-JSON textarea when there's no usable schema to build fields from
  // (missing, unparseable, or {}) — data-json-fallback marks that case
  // for runPrediction below.
  function jsonFieldsHtml(uid, inputSchema) {
    let schema = null;
    try {
      schema = JSON.parse(inputSchema);
    } catch (e) {
      schema = null;
    }
    const keys = schema && typeof schema === "object" ? Object.keys(schema) : [];

    if (!keys.length) {
      return (
        '<div class="field" style="margin-bottom:.4rem">' +
        '<label class="field-label" for="predict-input-' + uid + '">Input data (JSON)</label>' +
        '<textarea class="textarea" id="predict-input-' + uid + '" data-json-fallback="1" placeholder=\'{"field": "value"}\' style="font-size:var(--text-xs);min-height:3.5em"></textarea>' +
        "</div>"
      );
    }

    const fields = keys
      .map((key, idx) => {
        const fieldType = schema[key];
        const htmlInputType = String(fieldType || "").toLowerCase() === "number" ? "number" : "text";
        return (
          '<div class="field" style="margin-bottom:.4rem">' +
          '<label class="field-label" for="predict-field-' + uid + "-" + idx + '">' +
          UI.escapeHtml(key) +
          (fieldType ? ' <span class="text-muted">(' + UI.escapeHtml(String(fieldType)) + ")</span>" : "") +
          "</label>" +
          '<input class="input" type="' + htmlInputType + '" id="predict-field-' + uid + "-" + idx + '" data-field-key="' + UI.escapeHtml(key) + '" style="font-size:var(--text-xs)">' +
          "</div>"
        );
      })
      .join("");
    return '<div data-json-fields="' + uid + '">' + fields + "</div>";
  }

  function testerHtml(uid, inputType, inputSchema) {
    const inputHtml =
      inputType === "json"
        ? jsonFieldsHtml(uid, inputSchema)
        : '<div class="field" style="margin-bottom:.4rem">' +
          '<textarea class="textarea" id="predict-input-' + uid + '" placeholder="Enter text to analyze…" style="font-size:var(--text-xs);min-height:3.5em"></textarea>' +
          "</div>";
    return (
      inputHtml +
      '<button class="btn btn-secondary btn-sm" data-run="' + uid + '" type="button">Run prediction</button>' +
      '<div id="predict-result-' + uid + '" style="margin-top:.6rem"></div>' +
      '<a class="link-secondary" href="#" data-clear-key="' + uid + '" style="font-size:var(--text-xs);display:inline-block;margin-top:.5rem">Clear key</a>'
    );
  }

  // Full tester block for one team+deployment pair. `uid` must be unique
  // among every tester rendered on the same page (callers use
  // 'd' + deployment_id, which is unique per page in both call sites).
  // inputType/inputSchema come from the permission row; inputType
  // defaults to the plain-text tester for anything other than "json"
  // (covers "text", "file", and unset alike).
  function render(uid, teamId, deploymentId, inputType, inputSchema) {
    const hasKey = !!getKey(teamId, deploymentId);
    return (
      '<div class="predict-tester" id="predict-' + uid + '">' +
      (hasKey ? testerHtml(uid, inputType, inputSchema) : keyPromptHtml(uid)) +
      "</div>"
    );
  }

  /* ---- Wiring ------------------------------------------------------------*/

  // Attaches event listeners for one tester block — call once, right
  // after its render() output has been inserted into the DOM. Safe to
  // call again after the block's own innerHTML is swapped between the
  // key-prompt and tester states (only the elements that actually exist
  // in the current state are found and wired).
  function wire(uid, teamId, deploymentId, inputType, inputSchema) {
    const root = document.getElementById("predict-" + uid);
    if (!root) return;

    const saveBtn = root.querySelector('[data-save-key="' + uid + '"]');
    if (saveBtn) {
      const keyInput = document.getElementById("predict-key-" + uid);
      const save = () => {
        const value = (keyInput.value || "").trim();
        if (!value) return;
        setKey(teamId, deploymentId, value);
        root.innerHTML = testerHtml(uid, inputType, inputSchema);
        wire(uid, teamId, deploymentId, inputType, inputSchema);
      };
      saveBtn.addEventListener("click", save);
      keyInput.addEventListener("keydown", (e) => {
        if (e.key === "Enter") save();
      });
    }

    const runBtn = root.querySelector('[data-run="' + uid + '"]');
    if (runBtn) {
      runBtn.addEventListener("click", () => runPrediction(uid, teamId, deploymentId, inputType, inputSchema));
    }

    const clearLink = root.querySelector('[data-clear-key="' + uid + '"]');
    if (clearLink) {
      clearLink.addEventListener("click", (e) => {
        e.preventDefault();
        clearKey(teamId, deploymentId);
        root.innerHTML = keyPromptHtml(uid);
        wire(uid, teamId, deploymentId, inputType, inputSchema);
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

  // Reads the current form state into the {text: ...} or {data: ...}
  // body /api/v1/predict expects for this input_type. Returns null (after
  // showing an inline error) when there's nothing usable to send yet.
  function collectRequestBody(uid, deploymentId, inputType, resultEl) {
    if (inputType === "json") {
      const fieldsContainer = document.querySelector('[data-json-fields="' + uid + '"]');
      if (fieldsContainer) {
        const data = {};
        fieldsContainer.querySelectorAll("[data-field-key]").forEach((el) => {
          const key = el.dataset.fieldKey;
          const raw = el.value;
          data[key] = el.type === "number" && raw !== "" ? Number(raw) : raw;
        });
        return { data: data, deployment_id: deploymentId };
      }
      // No schema to build per-field inputs from — raw JSON textarea.
      const textarea = document.getElementById("predict-input-" + uid);
      const raw = (textarea.value || "").trim();
      if (!raw) {
        resultEl.innerHTML = '<div class="field-error" style="min-height:0">Enter some JSON data first.</div>';
        return null;
      }
      try {
        return { data: JSON.parse(raw), deployment_id: deploymentId };
      } catch (e) {
        resultEl.innerHTML = '<div class="field-error" style="min-height:0">That’s not valid JSON.</div>';
        return null;
      }
    }

    const input = document.getElementById("predict-input-" + uid);
    const text = (input.value || "").trim();
    if (!text) {
      resultEl.innerHTML = '<div class="field-error" style="min-height:0">Enter some text first.</div>';
      return null;
    }
    return { text: text, deployment_id: deploymentId };
  }

  async function runPrediction(uid, teamId, deploymentId, inputType, inputSchema) {
    const resultEl = document.getElementById("predict-result-" + uid);
    const btn = document.querySelector('[data-run="' + uid + '"]');

    const body = collectRequestBody(uid, deploymentId, inputType, resultEl);
    if (!body) return;

    const apiKey = getKey(teamId, deploymentId);
    const originalLabel = btn.textContent;
    btn.disabled = true;
    btn.textContent = "Running…";
    resultEl.innerHTML = '<span class="skeleton skeleton-text" style="display:inline-block;width:50%">&nbsp;</span>';

    try {
      const res = await fetch("/api/v1/predict", {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-API-Key": apiKey },
        body: JSON.stringify(body),
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
          wire(uid, teamId, deploymentId, inputType, inputSchema);
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
