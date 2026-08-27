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
 * Every entry carries `job` (and, for deployments behind the shared
 * PodMonitor, `pod`) — the Prometheus label selector Model Health/Drift
 * need to query that model's own metrics, not a static "is this
 * instrumented" flag. model-service's ServiceMonitor gives it a job all
 * to itself (job="model-service"); every model-runner/custom-runner
 * deployment shares ONE job (PLATFORM_RUNNER_JOB, from k8s/platform-
 * runner-podmonitor.yaml's own namespace/name — a PodMonitor covering
 * many dynamically-named deployments has no per-deployment job the way
 * a one-target ServiceMonitor does), disambiguated by `pod`, a regex
 * matching that deployment's pod-name prefix (pods are named
 * <deployment>-<replicaset-hash>-<random>). Whether a query for that
 * selector actually returns anything is then just a runtime fact
 * (checked by monitoring.js's metricsHaveData()), not assumed here.
 */

const ModelCatalog = (() => {
  const STORAGE_KEY = "vela:selectedModel";
  const PLATFORM_RUNNER_JOB = "monitoring/platform-runner-podmonitor";

  // Every fetch below is its own try/catch, and every entry-building loop
  // guards each item individually — a failing/unreachable endpoint or one
  // malformed record degrades the catalog (fewer entries) instead of
  // silently producing zero. Failures are logged, not swallowed: this
  // code used to fail totally silently on a bad response shape, which
  // made a real bug (or a stale cached copy of this very file) look like
  // "the picker just doesn't render" with nothing in the console.
  function pushCoreEntries(entries, core) {
    core.forEach((m) => {
      try {
        entries.push({
          key: "core:" + m.id, label: m.name, task: m.task, kind: "core",
          job: m.job, instrumented: !!m.instrumented, status: m.status,
        });
      } catch (e) {
        console.error("ModelCatalog: skipping malformed core entry", m, e);
      }
    });
  }

  async function loadForMember() {
    const entries = [];
    try {
      pushCoreEntries(entries, await Api.get("/models/status"));
    } catch (e) {
      console.error("ModelCatalog: GET /models/status failed", e);
    }

    let teams = [];
    try {
      teams = await Api.get("/users/me/teams");
    } catch (e) {
      console.error("ModelCatalog: GET /users/me/teams failed", e);
    }
    if (teams.length) {
      const perTeam = await Promise.allSettled(teams.map((t) => Api.get("/teams/" + t.id + "/permissions")));
      const byDeployment = new Map();
      perTeam.forEach((r) => {
        if (r.status !== "fulfilled") {
          console.error("ModelCatalog: GET /teams/{id}/permissions failed", r.reason);
          return;
        }
        r.value.forEach((p) => {
          if (p.is_active === false) return;
          if (!p.can_view_metrics && !p.can_predict) return;
          if (!byDeployment.has(p.deployment_id)) byDeployment.set(p.deployment_id, p);
        });
      });
      byDeployment.forEach((p) => {
        try {
          entries.push({
            key: "deployment:" + p.deployment_id,
            label: p.model_name, task: p.task_type,
            kind: p.model_type === "custom" ? "custom" : "huggingface",
            deploymentId: p.deployment_id, deploymentName: p.deployment_name,
            job: PLATFORM_RUNNER_JOB, pod: p.deployment_name + "-.*",
            instrumented: false, status: p.status,
          });
        } catch (e) {
          console.error("ModelCatalog: skipping malformed permission entry", p, e);
        }
      });
    }
    return entries;
  }

  async function loadForAdmin() {
    const entries = [];
    try {
      pushCoreEntries(entries, await Api.get("/models/status"));
    } catch (e) {
      console.error("ModelCatalog: GET /models/status failed", e);
    }

    let registry = [];
    try {
      registry = await Api.get("/admin/deployment-registry");
    } catch (e) {
      console.error("ModelCatalog: GET /admin/deployment-registry failed", e);
    }
    let live = [];
    try {
      live = await Api.get("/deployments");
    } catch (e) {
      console.error("ModelCatalog: GET /deployments failed", e);
    }
    const liveByName = new Map((live || []).map((d) => [d.name, d]));

    (registry || []).forEach((r) => {
      try {
        const l = liveByName.get(r.name);
        entries.push({
          key: "deployment:" + r.id,
          label: r.model_name || r.name, task: r.task_type,
          kind: r.model_type === "custom" ? "custom" : "huggingface",
          deploymentId: r.id, deploymentName: r.name,
          job: PLATFORM_RUNNER_JOB, pod: r.name + "-.*",
          instrumented: false,
          status: l ? l.status : r.status,
          replicas: l ? l.ready + "/" + l.desired : null,
          isActive: r.is_active,
        });
      } catch (e) {
        console.error("ModelCatalog: skipping malformed registry entry", r, e);
      }
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
