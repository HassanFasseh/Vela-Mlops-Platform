/*
 * Vela model catalog + picker — shared by Model Health (monitoring.js) and
 * Drift (drift.js), for both /app/* and /admin/* variants.
 *
 * Composes the same "list of models this viewer can see" client-side from
 * existing endpoints, the same way /app/models and /admin/deployments
 * already do — there is no single backend endpoint for this:
 *
 *   member: GET /models/status (the two public core services, available
 *            to every authenticated user — see /predict-proxy, which has
 *            no auth check either) + GET /users/me/teams -> GET
 *            /teams/{id}/permissions, filtered to is_active and
 *            (can_view_metrics or can_predict). can_view_metrics has
 *            existed on TeamModelPermission since the teams feature
 *            shipped but was never actually enforced anywhere until now.
 *
 *   admin:  GET /models/status + GET /admin/deployment-registry (every
 *            Deployment row, not team-scoped), enriched with GET
 *            /deployments for live k8s replica status on the
 *            platform-deployed (non-custom) ones.
 *
 * Every entry also carries `instrumented`: true only for the one
 * Prometheus job that's actually scraped today (see services/timeline.py
 * DEFAULT_JOB) — Model Health/Drift use this to decide whether to render
 * real charts or an honest "not instrumented" state, instead of ever
 * showing a fabricated zero.
 */

const ModelCatalog = (() => {
  const STORAGE_KEY = "vela:selectedModel";

  async function loadForMember() {
    const entries = [];
    try {
      const core = await Api.get("/models/status");
      core.forEach((m) =>
        entries.push({
          key: "core:" + m.id, label: m.name, task: m.task, kind: "core",
          job: m.job, instrumented: !!m.instrumented, status: m.status,
        })
      );
    } catch (e) {
      /* core services unreachable — fall through to whatever team grants exist */
    }

    let teams = [];
    try {
      teams = await Api.get("/users/me/teams");
    } catch (e) {
      teams = [];
    }
    if (teams.length) {
      const perTeam = await Promise.allSettled(teams.map((t) => Api.get("/teams/" + t.id + "/permissions")));
      const byDeployment = new Map();
      perTeam.forEach((r) => {
        if (r.status !== "fulfilled") return;
        r.value.forEach((p) => {
          if (p.is_active === false) return;
          if (!p.can_view_metrics && !p.can_predict) return;
          if (!byDeployment.has(p.deployment_id)) byDeployment.set(p.deployment_id, p);
        });
      });
      byDeployment.forEach((p) => {
        entries.push({
          key: "deployment:" + p.deployment_id,
          label: p.model_name, task: p.task_type,
          kind: p.model_type === "custom" ? "custom" : "huggingface",
          deploymentId: p.deployment_id, deploymentName: p.deployment_name,
          job: null, instrumented: false, status: p.status,
        });
      });
    }
    return entries;
  }

  async function loadForAdmin() {
    const entries = [];
    try {
      const core = await Api.get("/models/status");
      core.forEach((m) =>
        entries.push({
          key: "core:" + m.id, label: m.name, task: m.task, kind: "core",
          job: m.job, instrumented: !!m.instrumented, status: m.status,
        })
      );
    } catch (e) {
      /* fall through */
    }

    let registry = [];
    try {
      registry = await Api.get("/admin/deployment-registry");
    } catch (e) {
      registry = [];
    }
    let live = [];
    try {
      live = await Api.get("/deployments");
    } catch (e) {
      live = [];
    }
    const liveByName = new Map(live.map((d) => [d.name, d]));

    registry.forEach((r) => {
      const l = liveByName.get(r.name);
      entries.push({
        key: "deployment:" + r.id,
        label: r.model_name || r.name, task: r.task_type,
        kind: r.model_type === "custom" ? "custom" : "huggingface",
        deploymentId: r.id, deploymentName: r.name,
        job: null, instrumented: false,
        status: l ? l.status : r.status,
        replicas: l ? l.ready + "/" + l.desired : null,
        isActive: r.is_active,
      });
    });
    return entries;
  }

  function load(role) {
    return role === "admin" ? loadForAdmin() : loadForMember();
  }

  function getSelected() {
    const fromUrl = new URLSearchParams(location.search).get("model");
    if (fromUrl) return fromUrl;
    try {
      return localStorage.getItem(STORAGE_KEY);
    } catch (e) {
      return null;
    }
  }

  function setSelected(key) {
    try {
      localStorage.setItem(STORAGE_KEY, key);
    } catch (e) {
      /* private browsing etc — selection just won't survive a reload */
    }
    const url = new URL(location.href);
    url.searchParams.set("model", key);
    history.replaceState(null, "", url);
  }

  function kindLabel(kind) {
    return { core: "Core service", huggingface: "Deployment", custom: "Custom model" }[kind] || kind;
  }

  function pickDefault(entries, requestedKey) {
    if (requestedKey && entries.some((e) => e.key === requestedKey)) return requestedKey;
    return entries.length ? entries[0].key : null;
  }

  function renderPicker(containerId, entries, selectedKey, onChange) {
    const el = document.getElementById(containerId);
    if (!el) return;
    if (!entries.length) {
      el.innerHTML = "";
      return;
    }
    const options = entries
      .map(
        (e) =>
          '<option value="' + e.key + '"' + (e.key === selectedKey ? " selected" : "") + ">" +
          UI.escapeHtml(e.label) + " — " + UI.escapeHtml(kindLabel(e.kind)) +
          "</option>"
      )
      .join("");
    el.innerHTML =
      '<label class="field-label" for="model-picker-select" style="display:block;margin-bottom:4px">Model</label>' +
      '<select class="select" id="model-picker-select" style="min-width:280px">' + options + "</select>";
    document.getElementById("model-picker-select").addEventListener("change", (e) => onChange(e.target.value));
  }

  return { load, getSelected, setSelected, kindLabel, pickDefault, renderPicker };
})();
