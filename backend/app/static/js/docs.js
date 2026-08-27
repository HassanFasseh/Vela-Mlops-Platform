/*
 * Vela model documentation viewer — shared by /admin/docs and /app/docs
 * (spec §20). A dropdown of every model the viewer can see (admin: GET
 * /admin/deployment-registry; member: GET /users/me/teams -> GET
 * /teams/{id}/permissions, deduped and filtered to is_active) replaces
 * the old deployment-ID lookup form — the admin no longer needs to know
 * or type an ID, though it's still shown next to each name in the
 * dropdown ("clinical-sentiment (ID 16)") since it's what
 * /admin/remediation's "New config" and a few other places still ask
 * for directly.
 *
 * GET /model-cards/{deployment_id} has no auth check on the backend —
 * what differs by role here is purely which picker source is used and
 * whether an editable form renders below the card: admins get one
 * (POST /model-cards is an upsert keyed by deployment_id, so the same
 * form both creates and edits — see auth.py), members get a read-only
 * view or an empty state.
 */

const Docs = (() => {
  let role = "member";
  let entries = [];
  let selectedId = null;

  async function loadEntriesForAdmin() {
    const registry = await Api.get("/admin/deployment-registry");
    return registry.map((r) => ({ id: r.id, name: r.name }));
  }

  async function loadEntriesForMember() {
    let teams = [];
    try {
      teams = await Api.get("/users/me/teams");
    } catch (e) {
      console.error("Docs: GET /users/me/teams failed", e);
    }
    if (!teams.length) return [];
    const perTeam = await Promise.allSettled(teams.map((t) => Api.get("/teams/" + t.id + "/permissions")));
    const byId = new Map();
    perTeam.forEach((r) => {
      if (r.status !== "fulfilled") {
        console.error("Docs: GET /teams/{id}/permissions failed", r.reason);
        return;
      }
      r.value.forEach((p) => {
        if (p.is_active === false) return;
        if (!byId.has(p.deployment_id)) {
          byId.set(p.deployment_id, { id: p.deployment_id, name: p.deployment_name || p.model_name });
        }
      });
    });
    return Array.from(byId.values());
  }

  function renderPicker() {
    const sel = document.getElementById("docs-model-select");
    if (!entries.length) {
      sel.innerHTML = '<option value="">No models available</option>';
      sel.disabled = true;
      return;
    }
    sel.disabled = false;
    sel.innerHTML = entries
      .map(
        (e) =>
          '<option value="' + e.id + '"' + (String(e.id) === String(selectedId) ? " selected" : "") + ">" +
          UI.escapeHtml(e.name) + " (ID " + e.id + ")" +
          "</option>"
      )
      .join("");
  }

  function textOrPlaceholder(value) {
    return value
      ? '<p class="text-secondary" style="font-size:var(--text-sm);line-height:1.6;white-space:pre-wrap;margin:0">' + UI.escapeHtml(value) + "</p>"
      : '<span class="text-muted" style="font-size:var(--text-sm)">Not documented.</span>';
  }

  function section(title, bodyHtml) {
    return (
      '<div class="section-label">' + UI.escapeHtml(title) + "</div>" +
      '<div class="card" style="margin-bottom:var(--space-4)">' + bodyHtml + "</div>"
    );
  }

  function renderCardView(card) {
    const licenseBody = card.license
      ? UI.badge(card.license, "info")
      : '<span class="text-muted" style="font-size:var(--text-sm)">Not specified.</span>';
    const datasetBody =
      textOrPlaceholder(card.dataset) +
      (card.dataset_source
        ? '<div class="text-muted" style="font-size:var(--text-xs);margin-top:.5rem">Source: ' + UI.escapeHtml(card.dataset_source) + "</div>"
        : "");
    return (
      '<div class="text-muted" style="font-size:var(--text-xs);margin-bottom:var(--space-3)">Documented ' + UI.fmtDate(card.created_at) + "</div>" +
      section("Dataset", datasetBody) +
      section("License", licenseBody) +
      section("Performance", textOrPlaceholder(card.performance_notes)) +
      section("Limitations", textOrPlaceholder(card.limitations))
    );
  }

  function formHtml(card) {
    const c = card || {};
    return (
      '<div class="section-label">' + (card ? "Edit documentation" : "Add documentation") + "</div>" +
      '<div class="card">' +
      '<form id="card-form" novalidate>' +
      '<div class="field"><label class="field-label" for="mc-dataset">Dataset name</label><input class="input" id="mc-dataset" value="' + UI.escapeHtml(c.dataset || "") + '"></div>' +
      '<div class="field"><label class="field-label" for="mc-dataset-source">Dataset source</label><input class="input" id="mc-dataset-source" value="' + UI.escapeHtml(c.dataset_source || "") + '" placeholder="e.g. internal warehouse, HuggingFace Hub, https://..."></div>' +
      '<div class="field"><label class="field-label" for="mc-license">License</label><input class="input" id="mc-license" value="' + UI.escapeHtml(c.license || "") + '" placeholder="e.g. MIT, Apache 2.0, proprietary"></div>' +
      '<div class="field"><label class="field-label" for="mc-perf">Performance notes</label><textarea class="textarea" id="mc-perf">' + UI.escapeHtml(c.performance_notes || "") + "</textarea></div>" +
      '<div class="field"><label class="field-label" for="mc-limits">Known limitations</label><textarea class="textarea" id="mc-limits">' + UI.escapeHtml(c.limitations || "") + "</textarea></div>" +
      '<div class="field-error" id="mc-error" role="alert"></div>' +
      '<button class="btn btn-primary btn-sm" type="submit">Save</button>' +
      "</form>" +
      "</div>"
    );
  }

  function wireForm(id) {
    const form = document.getElementById("card-form");
    if (!form) return;
    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      const errorEl = document.getElementById("mc-error");
      errorEl.textContent = "";
      const submitBtn = form.querySelector('button[type="submit"]');
      submitBtn.disabled = true;
      try {
        await Api.post("/model-cards", {
          deployment_id: parseInt(id, 10),
          dataset: document.getElementById("mc-dataset").value.trim(),
          dataset_source: document.getElementById("mc-dataset-source").value.trim(),
          license: document.getElementById("mc-license").value.trim(),
          performance_notes: document.getElementById("mc-perf").value.trim(),
          limitations: document.getElementById("mc-limits").value.trim(),
        });
        UI.toast("Model card saved", "success");
        selectModel(id);
      } catch (err) {
        errorEl.textContent = err.message || "Could not save model card.";
        submitBtn.disabled = false;
      }
    });
  }

  async function selectModel(id) {
    selectedId = id;
    const params = new URLSearchParams(location.search);
    params.set("deployment_id", id);
    history.replaceState(null, "", location.pathname + "?" + params.toString());
    renderPicker();

    const resultEl = document.getElementById("card-result");
    resultEl.innerHTML = '<div class="card"><span class="skeleton skeleton-text" style="display:block;max-width:220px">&nbsp;</span></div>';

    let card = null;
    try {
      card = await Api.get("/model-cards/" + id);
    } catch (e) {
      if (e.status !== 404) {
        resultEl.innerHTML = UI.errorState(e.message, () => selectModel(id));
        return;
      }
    }

    if (role === "admin") {
      resultEl.innerHTML = (card ? renderCardView(card) : "") + formHtml(card);
      wireForm(id);
    } else if (card) {
      resultEl.innerHTML = renderCardView(card);
    } else {
      resultEl.innerHTML = UI.emptyState("No documentation available yet", "This model hasn't been documented yet.");
    }
  }

  async function start(opts) {
    role = (opts && opts.role) || "member";
    const subtitleEl = document.getElementById("docs-subtitle");
    if (subtitleEl) {
      subtitleEl.textContent = role === "admin" ? "Select a model to view or document it." : "Select a model to view its documentation.";
    }

    try {
      entries = role === "admin" ? await loadEntriesForAdmin() : await loadEntriesForMember();
    } catch (e) {
      document.getElementById("card-result").innerHTML = UI.errorState(e.message, () => start(opts));
      return;
    }

    if (!entries.length) {
      renderPicker();
      document.getElementById("card-result").innerHTML = UI.emptyState(
        "No models available",
        role === "admin" ? "Deploy a model first." : "Your team hasn't been granted model access yet."
      );
      return;
    }

    const params = new URLSearchParams(location.search);
    const pre = params.get("deployment_id");
    const initial = pre && entries.some((e) => String(e.id) === pre) ? pre : String(entries[0].id);

    selectedId = initial;
    renderPicker();
    document.getElementById("docs-model-select").addEventListener("change", (e) => selectModel(e.target.value));
    selectModel(initial);
  }

  return { start };
})();
