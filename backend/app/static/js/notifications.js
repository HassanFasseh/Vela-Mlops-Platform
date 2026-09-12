/*
 * Vela notification center - aggregates real alert-worthy events from the
 * endpoints that already exist (there is no dedicated notifications
 * endpoint/table). Admin-only: wired from shell.js only when role ===
 * "admin"; the bell/panel markup is hidden entirely for members.
 *
 * Two kinds of source, deliberately not blurred together:
 *   - EVENTS, with a real timestamp, sorted newest-first:
 *       - drift-triggered remediation actions (GET /api/v1/
 *         remediation-logs/{workspace_id}, same per-workspace fan-out
 *         admin_remediation_page uses) - RemediationLog.triggered_at.
 *       - unresolved critical/high tickets (GET /admin/tickets) -
 *         Ticket.filed_at.
 *   - STATUS FACTS, with no history to draw a timestamp from - shown
 *     with an "Ongoing" tag instead of a fabricated relative time:
 *       - deployments currently status === "failed" (GET /admin/
 *         deployment-registry) - Deployment has no failed_at column,
 *         this is only ever a live snapshot.
 *       - models currently unreachable (GET /models/status) - a live
 *         per-pod health probe, also no history. This one does a real
 *         HTTP call per deployment with a 3s timeout each, so unlike
 *         everything else here it is NOT fetched on every page load -
 *         only when the panel is actually opened (see onPanelOpen).
 *
 * Read-state is client-side only (localStorage) - there's no server-side
 * notifications table to persist it in. Two pieces: a set of
 * individually-read ids, and a "read before" timestamp that "Mark all
 * read" bumps to now. An EVENT counts as read if either applies. A
 * STATUS FACT has no timestamp, so it can only ever be read via its id -
 * meaning once acknowledged, a status fact with the same id (e.g. the
 * same deployment failing again later) will NOT re-alert. That's an
 * accepted limitation of tracking read-state without a real server-side
 * event log, not a bug to engineer around here.
 */

const Notifications = (() => {
  const READ_IDS_KEY = "vela_notif_read_ids";
  const READ_BEFORE_KEY = "vela_notif_read_before";

  const ACTION_LABEL = { github_issue: "GitHub issue", webhook: "Webhook", retrain: "Retrain" };
  const TICKET_SEVERITY_VARIANT = { critical: "error", high: "warning", medium: "neutral", low: "neutral" };

  let els = null;
  let items = [];            // cheap sources: events + failed deploys
  let cheapError = false;
  let healthItems = [];      // expensive source: live health probe
  let healthLoaded = false;
  let healthLoading = false;

  function readIds() {
    try { return new Set(JSON.parse(localStorage.getItem(READ_IDS_KEY) || "[]")); }
    catch (e) { return new Set(); }
  }
  function saveReadIds(ids) {
    try { localStorage.setItem(READ_IDS_KEY, JSON.stringify(Array.from(ids))); } catch (e) {}
  }
  function readBefore() {
    try {
      const v = localStorage.getItem(READ_BEFORE_KEY);
      return v ? new Date(v).getTime() : 0;
    } catch (e) { return 0; }
  }
  function setReadBefore(ts) {
    try { localStorage.setItem(READ_BEFORE_KEY, new Date(ts).toISOString()); } catch (e) {}
  }
  function isRead(n, ids, before) {
    return ids.has(n.id) || (n.time != null && n.time <= before);
  }

  function toMs(iso) {
    if (!iso) return null;
    const d = new Date(iso.endsWith && iso.endsWith("Z") ? iso : iso + "Z");
    return isNaN(d.getTime()) ? null : d.getTime();
  }

  async function loadCheap() {
    const registry = await Api.get("/admin/deployment-registry");
    const depLabel = (id) => {
      const d = registry.find((r) => r.id === id);
      return d ? (d.model_name || d.name) : "Deployment #" + id;
    };
    const workspaceIds = Array.from(new Set(registry.map((d) => d.workspace_id).filter((id) => id != null)));

    const [logResults, tickets] = await Promise.all([
      Promise.allSettled(workspaceIds.map((ws) => Api.get("/api/v1/remediation-logs/" + ws))),
      Api.get("/admin/tickets"),
    ]);
    const logs = logResults.filter((r) => r.status === "fulfilled").flatMap((r) => r.value);

    const fromLogs = logs.map((l) => {
      const isError = String(l.status).toLowerCase() === "error";
      const action = ACTION_LABEL[l.action_type] || l.action_type;
      return {
        id: "rlog:" + l.id,
        time: toMs(l.triggered_at),
        severity: isError ? "error" : "drift",
        title: action + (isError ? " failed for " : " triggered for ") + depLabel(l.deployment_id),
        href: "/admin/remediation",
      };
    });

    const fromTickets = tickets
      .filter((t) => (t.severity === "critical" || t.severity === "high") && t.status !== "resolved" && t.status !== "closed")
      .map((t) => ({
        id: "ticket:" + t.id,
        time: toMs(t.filed_at),
        severity: TICKET_SEVERITY_VARIANT[t.severity] || "neutral",
        title: "New " + t.severity + " ticket: " + t.title,
        href: "/admin/tickets-page",
      }));

    const fromFailedDeploys = registry
      .filter((d) => d.status === "failed")
      .map((d) => ({
        id: "deploy-failed:" + d.id,
        time: null,
        severity: "error",
        title: 'Deployment "' + (d.model_name || d.name) + '" failed',
        href: "/admin/deployments",
      }));

    items = fromLogs.concat(fromTickets, fromFailedDeploys);
  }

  async function loadHealth() {
    const statuses = await Api.get("/models/status");
    healthItems = statuses
      .filter((s) => s.status === "offline")
      .map((s) => ({
        id: "health-offline:" + s.id,
        time: null,
        severity: "warning",
        title: '"' + (s.model || s.name) + '" is unreachable',
        href: "/admin/monitoring",
      }));
  }

  function allItems() {
    return items.concat(healthItems);
  }

  // Newest event first; untimed status facts sort after every timestamped
  // event, in whatever order loadHealth/loadCheap produced them.
  function sortedItems() {
    return allItems().slice().sort((a, b) => {
      if (a.time == null && b.time == null) return 0;
      if (a.time == null) return 1;
      if (b.time == null) return -1;
      return b.time - a.time;
    });
  }

  function unreadCount() {
    const ids = readIds(), before = readBefore();
    return allItems().filter((n) => !isRead(n, ids, before)).length;
  }

  function updateDot() {
    if (els && els.dotEl) els.dotEl.hidden = unreadCount() === 0;
  }

  function rowHtml(n, read) {
    const timeText = n.time != null ? UI.timeAgo(new Date(n.time).toISOString()) : "Ongoing";
    return (
      '<div class="shell-notif-row' + (read ? "" : " is-unread") + '" data-notif-id="' + n.id + '" data-notif-href="' + n.href + '">' +
      '<span class="status-dot status-dot-' + n.severity + '" aria-hidden="true"><span class="status-dot-mark"></span></span>' +
      '<span class="shell-notif-row-body">' +
      '<span class="shell-notif-row-title">' + UI.escapeHtml(n.title) + "</span>" +
      '<span class="shell-notif-row-time">' + UI.escapeHtml(timeText) + "</span>" +
      "</span>" +
      '<button class="shell-notif-row-check" data-notif-mark="' + n.id + '" type="button" aria-label="Mark as read" title="Mark as read">' +
      Shell.icon("check") +
      "</button>" +
      "</div>"
    );
  }

  function render() {
    if (!els) return;
    const rows = sortedItems();
    if (cheapError && !rows.length) {
      els.bodyEl.innerHTML = UI.errorState("Could not load notifications.", retry);
      return;
    }
    if (!rows.length) {
      els.bodyEl.innerHTML = UI.emptyState("You're all caught up", "No alerts right now.");
    } else {
      const ids = readIds(), before = readBefore();
      let html = rows.map((n) => rowHtml(n, isRead(n, ids, before))).join("");
      if (healthLoading) {
        html += '<div class="shell-notif-checking">Checking model health&hellip;</div>';
      }
      els.bodyEl.innerHTML = html;
    }
    els.bodyEl.querySelectorAll(".shell-notif-row").forEach((row) => {
      row.addEventListener("click", (e) => {
        if (e.target.closest("[data-notif-mark]")) return;
        markRead(row.dataset.notifId);
        window.location.href = row.dataset.notifHref;
      });
    });
    els.bodyEl.querySelectorAll("[data-notif-mark]").forEach((btn) => {
      btn.addEventListener("click", (e) => {
        e.stopPropagation();
        markRead(btn.dataset.notifMark);
        render();
        updateDot();
      });
    });
  }

  function markRead(id) {
    const ids = readIds();
    ids.add(id);
    saveReadIds(ids);
  }

  function markAllRead() {
    const ids = readIds();
    allItems().forEach((n) => ids.add(n.id));
    saveReadIds(ids);
    setReadBefore(Date.now());
    render();
    updateDot();
  }

  async function retry() {
    await init(els);
  }

  // Called once on shell mount (admin only) - cheap sources only, so the
  // unread dot is accurate everywhere without adding the expensive
  // health probe to every navigation.
  async function init(elements) {
    els = elements;
    cheapError = false;
    try {
      await loadCheap();
    } catch (e) {
      console.error("Notifications: cheap-source load failed", e);
      items = [];
      cheapError = true;
    }
    render();
    updateDot();
  }

  // Called every time the panel is opened. Renders immediately with
  // whatever's already loaded, then runs the health probe once per
  // mount (not on every open) and re-renders when it resolves.
  async function onPanelOpen() {
    render();
    if (healthLoaded || healthLoading) return;
    healthLoading = true;
    render();
    try {
      await loadHealth();
    } catch (e) {
      console.error("Notifications: health check failed", e);
      healthItems = [];
    }
    healthLoaded = true;
    healthLoading = false;
    render();
    updateDot();
  }

  return { init, onPanelOpen, markAllRead };
})();
