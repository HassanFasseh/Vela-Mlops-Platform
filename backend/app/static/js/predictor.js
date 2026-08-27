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
 *   "text" (default) — a plain textarea, {"text": ...}.
 *   "json" — input_schema is a JSON string like {"f1":"number"} stored
 *           on the deployment; parsed into one input field per key. No
 *           usable schema (missing/unparseable/empty) falls back to a
 *           raw-JSON textarea instead of losing the ability to predict
 *           entirely. Either way, sent as {"data": {...}}.
 *   "file" — images and audio. A <input type=file>; the selected file
 *           is read client-side into a base64 string (pendingFiles
 *           below) as soon as it's chosen, then sent as {"file": ...}.
 *
 * Calls go through the shared Api helper, which attaches the member's
 * own JWT (already how every other page here authenticates) — no
 * separate model API key needed in-app. /api/v1/predict accepts that
 * JWT as an alternative to X-API-Key and checks the same
 * TeamModelPermission.can_predict a key would need (see
 * check_user_predict_permission in services/teams.py). team_id is kept
 * in this module's signature only for call-site compatibility with
 * member_pages.py; it's not otherwise used here — permission is
 * resolved server-side from the JWT's user across all of their teams.
 */

const Predictor = (() => {
  // uid -> base64 string (no "data:...;base64," prefix) of the file
  // currently selected for a "file" input_type tester. Populated by the
  // file input's change handler in wire() below, read by
  // collectRequestBody — kept out of the DOM rather than stashed on the
  // input element since it can be a multi-MB string.
  const pendingFiles = {};

  function readFileAsBase64(file) {
    return new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => {
        const result = reader.result || "";
        const comma = result.indexOf(",");
        resolve(comma !== -1 ? result.slice(comma + 1) : result);
      };
      reader.onerror = () => reject(reader.error || new Error("Could not read file"));
      reader.readAsDataURL(file);
    });
  }

  /* ---- Markup ----------------------------------------------------------*/

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

  // <input type=file> — accepts images and audio since "file" covers
  // both (see model-runner/main.py's IMAGE_TASKS/AUDIO_TASKS). Actually
  // reading the file happens in wire()'s change handler, not here.
  function fileFieldHtml(uid) {
    return (
      '<div class="field" style="margin-bottom:.4rem">' +
      '<label class="field-label" for="predict-file-' + uid + '">Upload an image or audio file</label>' +
      '<input class="input" type="file" id="predict-file-' + uid + '" accept="image/*,audio/*" style="font-size:var(--text-xs)">' +
      '<div id="predict-file-status-' + uid + '" class="text-muted" style="font-size:var(--text-xs);margin-top:.3rem"></div>' +
      "</div>"
    );
  }

  function testerHtml(uid, inputType, inputSchema) {
    const inputHtml =
      inputType === "json"
        ? jsonFieldsHtml(uid, inputSchema)
        : inputType === "file"
        ? fileFieldHtml(uid)
        : '<div class="field" style="margin-bottom:.4rem">' +
          '<textarea class="textarea" id="predict-input-' + uid + '" placeholder="Enter text to analyze…" style="font-size:var(--text-xs);min-height:3.5em"></textarea>' +
          "</div>";
    return (
      inputHtml +
      '<button class="btn btn-secondary btn-sm" data-run="' + uid + '" type="button">Run prediction</button>' +
      '<div id="predict-result-' + uid + '" style="margin-top:.6rem"></div>'
    );
  }

  // Full tester block for one team+deployment pair. `uid` must be unique
  // among every tester rendered on the same page (callers use
  // 'd' + deployment_id, which is unique per page in both call sites).
  // inputType/inputSchema come from the permission row; inputType
  // defaults to the plain-text tester for anything other than "json" or
  // "file" (covers "text" and unset alike). teamId is unused (see the
  // module comment) but kept in the signature for call-site compatibility.
  function render(uid, teamId, deploymentId, inputType, inputSchema) {
    return '<div class="predict-tester" id="predict-' + uid + '">' + testerHtml(uid, inputType, inputSchema) + "</div>";
  }

  /* ---- Wiring ------------------------------------------------------------*/

  // Attaches event listeners for one tester block — call once, right
  // after its render() output has been inserted into the DOM.
  function wire(uid, teamId, deploymentId, inputType, inputSchema) {
    const root = document.getElementById("predict-" + uid);
    if (!root) return;

    const runBtn = root.querySelector('[data-run="' + uid + '"]');
    if (runBtn) {
      runBtn.addEventListener("click", () => runPrediction(uid, deploymentId, inputType, inputSchema));
    }

    const fileInput = document.getElementById("predict-file-" + uid);
    if (fileInput) {
      fileInput.addEventListener("change", async () => {
        const statusEl = document.getElementById("predict-file-status-" + uid);
        const file = fileInput.files && fileInput.files[0];
        delete pendingFiles[uid];
        if (!file) {
          if (statusEl) statusEl.textContent = "";
          return;
        }
        if (statusEl) statusEl.textContent = "Reading " + file.name + "…";
        try {
          pendingFiles[uid] = await readFileAsBase64(file);
          if (statusEl) statusEl.textContent = file.name + " ready (" + Math.round(file.size / 1024) + " KB)";
        } catch (e) {
          if (statusEl) statusEl.textContent = "Could not read that file.";
        }
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
      // Zero-shot, image-classification, audio-classification, ... —
      // anything model-runner's normalize_output gave a full ranking to.
      // Ranked labels as a small bar chart.
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
    if (result.result !== undefined) {
      // Every other HuggingFace pipeline task (text-generation,
      // summarization, translation, question-answering, fill-mask,
      // token-classification, image-classification, ...) — model-runner
      // returns each one's own raw pipeline output under "result" rather
      // than a bespoke shape per task, so there's no single "the answer"
      // field to pull out here either. Shown as legible formatted JSON
      // instead of silently looking like nothing came back.
      return (
        '<pre style="white-space:pre-wrap;word-break:break-word;font-size:var(--text-xs);margin:0;font-family:var(--font-mono)">' +
        UI.escapeHtml(JSON.stringify(result.result, null, 2)) +
        "</pre>"
      );
    }
    return '<div class="text-muted" style="font-size:var(--text-xs)">No result returned.</div>';
  }

  // Reads the current form state into the {text: ...}, {data: ...}, or
  // {file: ...} body /api/v1/predict expects for this input_type.
  // Returns null (after showing an inline error) when there's nothing
  // usable to send yet.
  function collectRequestBody(uid, deploymentId, inputType, resultEl) {
    if (inputType === "file") {
      const base64 = pendingFiles[uid];
      if (!base64) {
        resultEl.innerHTML = '<div class="field-error" style="min-height:0">Choose a file first.</div>';
        return null;
      }
      return { file: base64, deployment_id: deploymentId };
    }

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

  async function runPrediction(uid, deploymentId, inputType, inputSchema) {
    const resultEl = document.getElementById("predict-result-" + uid);
    const btn = document.querySelector('[data-run="' + uid + '"]');

    const body = collectRequestBody(uid, deploymentId, inputType, resultEl);
    if (!body) return;

    const originalLabel = btn.textContent;
    btn.disabled = true;
    btn.textContent = "Running…";
    resultEl.innerHTML = '<span class="skeleton skeleton-text" style="display:inline-block;width:50%">&nbsp;</span>';

    try {
      // Api.post attaches the member's JWT automatically and already
      // redirects to /login on a real 401 (session expired) — nothing
      // extra to handle here for that case.
      const data = await Api.post("/api/v1/predict", body);
      resultEl.innerHTML = renderResult((data && data.result) || {});
    } catch (e) {
      if (e.status !== 401) {
        resultEl.innerHTML = '<div class="field-error">' + UI.escapeHtml(e.message || "Request failed") + "</div>";
      }
    } finally {
      btn.disabled = false;
      btn.textContent = originalLabel;
    }
  }

  return { render, wire };
})();
