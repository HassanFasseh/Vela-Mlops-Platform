/*
 * Vela model documentation viewer — shared by /admin/docs and /app/docs
 * (spec §20). Wired to GET /model-cards/{deployment_id}, which is public
 * on the backend but still gated behind page-level auth like every other
 * page here.
 *
 * There is no endpoint to list or search deployment IDs (the same gap
 * noted on the Teams, Models, and Remediation pages), so this is a
 * lookup-by-ID form rather than a browsable catalog — an honest reflection
 * of what the API actually supports today.
 */

const Docs = (() => {
  let role = "member";

  function renderInitial() {
    document.getElementById("card-result").innerHTML = UI.emptyState(
      "Look up a model card",
      "Enter a deployment ID above to view its documentation."
    );
  }

  // A 404 here just means nobody's documented this deployment yet — not
  // a broken page. Copy differs by role: an admin can actually go create
  // one, a member can't, so pointing them at the Models page too would
  // be a dead end.
  function renderNotFound(id) {
    document.getElementById("card-result").innerHTML = UI.emptyState(
      "No model card found",
      role === "admin"
        ? "No model card found for this deployment. You can create one from the Models page."
        : "No model card available for this model yet."
    );
  }

  function renderError(message, id) {
    document.getElementById("card-result").innerHTML = UI.errorState(message, () => lookup(id));
  }

  function section(title, bodyHtml) {
    return (
      '<div class="section-label">' + UI.escapeHtml(title) + "</div>" +
      '<div class="card" style="margin-bottom:var(--space-4)">' + bodyHtml + "</div>"
    );
  }

  function textOrPlaceholder(value) {
    return value ? '<p class="text-secondary" style="font-size:var(--text-sm);line-height:1.6;white-space:pre-wrap;margin:0">' + UI.escapeHtml(value) + "</p>"
                 : '<span class="text-muted" style="font-size:var(--text-sm)">Not documented.</span>';
  }

  function renderCard(card) {
    const tags = (card.tags || "").split(",").map((t) => t.trim()).filter(Boolean);
    const header =
      '<div class="card" style="margin-bottom:var(--space-4)">' +
      '<div class="card-header"><div>' +
      '<div class="card-title">Deployment #' + card.deployment_id + "</div>" +
      '<div class="card-subtitle">Documented ' + UI.fmtDate(card.created_at) + "</div>" +
      "</div></div>" +
      (tags.length ? tags.map((t) => UI.badge(t, "neutral")).join(" ") : "") +
      "</div>";

    const licenseBody = card.license
      ? UI.badge(card.license, "info")
      : '<span class="text-muted" style="font-size:var(--text-sm)">Not specified.</span>';

    const datasetBody =
      textOrPlaceholder(card.dataset) +
      (card.dataset_size ? '<div class="text-muted" style="font-size:var(--text-xs);margin-top:.5rem">Size: ' + UI.escapeHtml(card.dataset_size) + "</div>" : "");

    document.getElementById("card-result").innerHTML =
      header +
      section("Overview", textOrPlaceholder(card.description)) +
      section("Dataset", datasetBody) +
      section("License", licenseBody) +
      section("Performance", textOrPlaceholder(card.performance_notes)) +
      section("Limitations", textOrPlaceholder(card.limitations));
  }

  async function lookup(id) {
    const params = new URLSearchParams(location.search);
    params.set("deployment_id", id);
    history.replaceState(null, "", location.pathname + "?" + params.toString());

    document.getElementById("card-result").innerHTML =
      '<div class="card"><span class="skeleton skeleton-text" style="display:block;max-width:220px">&nbsp;</span></div>';
    try {
      const card = await Api.get("/model-cards/" + id);
      renderCard(card);
    } catch (e) {
      if (e.status === 404) renderNotFound(id);
      else renderError(e.message, id);
    }
  }

  function start(opts) {
    role = (opts && opts.role) || "member";
    renderInitial();
    document.getElementById("lookup-form").addEventListener("submit", (e) => {
      e.preventDefault();
      const id = document.getElementById("dep-id").value.trim();
      if (id) lookup(id);
    });
    const params = new URLSearchParams(location.search);
    const pre = params.get("deployment_id");
    if (pre) {
      document.getElementById("dep-id").value = pre;
      lookup(pre);
    }
  }

  return { start };
})();
