"""
Admin HTML pages (spec §7/§8): Overview, Users, Teams, Tickets.

These are separate from the JSON /admin/* API defined in main.py - note the
"-page" suffix on Users/Teams/Tickets, which avoids colliding with the
existing GET /admin/users, /admin/teams, /admin/tickets JSON routes
(Starlette matches routes in registration order; a same-path HTML page
would silently shadow or be shadowed by the JSON API). /admin itself has
no such collision, so the Overview page keeps the clean path.

Like the rest of this codebase, pages are raw HTML strings - no template
engine, no build step. Each page loads the shared design system + AppShell
from /static, then fetches its data client-side from the existing API.
"""

from fastapi import APIRouter
from fastapi.responses import HTMLResponse, RedirectResponse

from backend.app.routers._page_fragments import (
    DS_ASSETS, CHART_JS_CDN, MONITORING_CSS, MONITORING_BODY, MONITORING_SCRIPTS_EXTRA,
    DOCS_SCRIPTS_EXTRA,
    SETTINGS_SCRIPTS_EXTRA,
)

router = APIRouter()

_ASSETS = """<link rel="stylesheet" href="/static/css/tokens.css?v=8">
<link rel="stylesheet" href="/static/css/base.css?v=8">
<link rel="stylesheet" href="/static/css/components.css?v=8">
<link rel="stylesheet" href="/static/css/shell.css?v=8">"""

_SCRIPTS = """<script src="/static/js/api.js?v=8"></script>
<script src="/static/js/shell.js?v=10"></script>
<script src="/static/js/ui.js?v=8"></script>"""

# Shared boot sequence: authenticate, require is_admin, mount the shell.
# Pages call ADMIN_BOOT(activePath, breadcrumbLabel) then their own loader.
_DENIED_ICON = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6"><path d="M12 3 L21 19 H3 Z" stroke-linejoin="round"/><line x1="12" y1="9" x2="12" y2="14"/><circle cx="12" cy="17" r=".6" fill="currentColor" stroke="none"/></svg>'


def _boot_script(active_path: str, breadcrumb_label: str, on_ready: str) -> str:
    """Build the standard admin-page bootstrap: auth -> admin gate -> shell mount -> loader."""
    return """
<script>
  (async function boot() {
    const user = await Api.requireAuth();
    if (!user) return;
    const content = document.getElementById('page-content');
    if (!user.is_admin) {
      content.hidden = false;
      content.innerHTML = '<div class="denied-state" style="margin-top:15vh">' +
        '<div class="denied-state-icon">""" + _DENIED_ICON + """</div>' +
        '<div class="empty-state-title">Admin access required</div>' +
        '<div class="empty-state-body">This section is only available to administrators. If you believe this is a mistake, contact your admin.</div>' +
        '<a class="btn btn-secondary btn-sm" href="/login" style="margin-top:1rem">Back to login</a>' +
        '</div>';
      return;
    }
    Shell.mount({
      user: user,
      activePath: '""" + active_path + """',
      breadcrumbs: [{label: 'Admin', href: '/admin'}, {label: '""" + breadcrumb_label + """'}],
    });
    """ + on_ready + """
  })();
</script>"""


# =========================================================================
# Overview - /admin
# =========================================================================

@router.get("/admin", response_class=HTMLResponse)
def admin_overview_page():
    # Phase 2: first screen migrated to the ds/* design system. This route
    # loads the ds/* stylesheet bundle instead of the legacy css/* one;
    # every other admin page still uses _ASSETS. The shared JS (_SCRIPTS:
    # api/shell/ui.js) is theme-agnostic and unchanged.
    ds_assets = (
        '<link rel="stylesheet" href="/static/css/ds/tokens.css?v=ds4">\n'
        '<link rel="stylesheet" href="/static/css/ds/base.css?v=ds4">\n'
        '<link rel="stylesheet" href="/static/css/ds/primitives.css?v=ds4">\n'
        '<link rel="stylesheet" href="/static/css/ds/shell.css?v=ds7">'
    )

    body = """
<div id="page-content" hidden>
  <div class="page-max">
    <div class="page-header">
      <div>
        <h1 class="page-title" id="greeting">Loading…</h1>
        <div class="page-description" id="platform-status"></div>
      </div>
      <div class="page-actions">
        <button class="btn btn-secondary btn-sm" id="refresh-btn" type="button">Refresh</button>
      </div>
    </div>

    <div class="metric-strip" id="metric-row"></div>

    <div class="section-label">Model health</div>
    <div id="drift-banner"></div>
    <div class="table-wrap">
      <table class="table" style="min-width:640px">
        <thead>
          <tr><th>Model</th><th>Task</th><th>Source</th><th>Status</th><th>Actions</th></tr>
        </thead>
        <tbody id="model-health-body"></tbody>
      </table>
    </div>

    <div class="section-label">Recent tickets</div>
    <div id="recent-tickets"></div>
  </div>
</div>
<div id="loading-root" style="min-height:100vh;display:flex;align-items:center;justify-content:center;color:var(--text-muted);font-size:var(--text-sm)">Loading&hellip;</div>
"""

    script = """
<script>
  function fmtPct(x) { return (x == null || isNaN(x)) ? '—' : (x * 100).toFixed(1) + '%'; }

  let overviewRows = [];
  let managementApiKey = '';
  let overviewUser = null;

  function initOverview(user) {
    const refreshBtn = document.getElementById('refresh-btn');
    if (refreshBtn) refreshBtn.addEventListener('click', () => loadOverview());
    loadOverview(user);
  }

  async function loadOverview(user) {
    overviewUser = user || overviewUser;
    document.getElementById('greeting').textContent = greetingFor(overviewUser);
    const results = await Promise.allSettled([
      Api.get('/admin/users'),
      Api.get('/admin/tickets'),
      Api.get('/admin/deployment-registry'),
      Api.get('/models/status'),
      Api.get('/metrics-summary'),
    ]);
    const [usersR, ticketsR, registryR, liveR, metricsR] = results;
    const users = usersR.status === 'fulfilled' ? usersR.value : [];
    const tickets = ticketsR.status === 'fulfilled' ? ticketsR.value : [];
    const registry = registryR.status === 'fulfilled' ? registryR.value : [];
    const live = liveR.status === 'fulfilled' ? liveR.value : [];
    const metrics = metricsR.status === 'fulfilled' ? metricsR.value : {};

    // Every model on the platform is a real Deployment row now - GET
    // /admin/deployment-registry is the full list, GET /models/status is
    // just a live health overlay on top of it (matched by id). There is
    // no separate "core service" catalog to merge in any more.
    const liveById = new Map(live.map(m => [m.id, m]));
    const rows = registry.map(r => {
      const l = liveById.get(r.id);
      return { id: r.id, name: r.name, task: r.task_type, model_type: r.model_type, is_active: r.is_active, status: l ? l.status : r.status, backing_model: l ? l.model : null };
    });
    overviewRows = rows;

    renderStatus(rows);
    renderMetrics(tickets, rows, metrics);
    renderDriftBanner(metrics);
    renderModelHealth(rows);
    renderRecentTickets(tickets);
  }

  function greetingFor(user) {
    const h = new Date().getHours();
    const part = h < 12 ? 'Good morning' : h < 18 ? 'Good afternoon' : 'Good evening';
    return part + ', ' + (user.name || user.username);
  }

  function renderStatus(rows) {
    const el = document.getElementById('platform-status');
    if (!rows.length) {
      el.innerHTML = UI.statusDot('Unknown', 'neutral') + ' <span class="text-muted">no models deployed yet</span>';
      return;
    }
    const offline = rows.filter(r => r.status !== 'online' && r.status !== 'running').length;
    if (offline === 0) {
      el.innerHTML = UI.statusDot('Operational', 'running');
    } else {
      el.innerHTML = UI.statusDot('Degraded', 'error') + ' <span class="text-muted">' + offline + ' of ' + rows.length + ' models offline</span>';
    }
  }

  // A plain-text 3-column strip (spec) instead of a KPI card wall -
  // total running models, open tickets, and platform-wide drift, each
  // just a number + label separated by a divider. Neutral by default: a
  // value only takes colour when it is itself the exception being
  // reported (open tickets, elevated platform drift).
  function stripItem(value, label, variant) {
    return '<div class="metric-strip-item"><div class="metric-strip-value' + (variant ? ' is-' + variant : '') + '">' + value + '</div><div class="metric-strip-label">' + label + '</div></div>';
  }

  function renderMetrics(tickets, rows, metrics) {
    const running = rows.filter(r => r.status === 'online' || r.status === 'running').length;
    const openTickets = tickets.filter(t => t.status === 'open' || t.status === 'investigating').length;
    document.getElementById('metric-row').innerHTML =
      stripItem(running + ' / ' + rows.length, 'Models running') +
      stripItem(openTickets, 'Open tickets', openTickets > 0 ? 'warning' : undefined) +
      stripItem(fmtPct(metrics.drift_score), 'Platform drift', (metrics.drift_score || 0) > 0.3 ? 'error' : undefined);
  }

  // There's no per-model drift breakdown fetched on this page (that lives
  // on /admin/monitoring's drift section, one model at a time) - only a
  // platform-wide drift_score from /metrics-summary. Rather than invent a
  // specific model name for the banner, this reflects what's actually
  // known: the platform-wide figure crossing a threshold.
  function renderDriftBanner(metrics) {
    const el = document.getElementById('drift-banner');
    if ((metrics.drift_score || 0) <= 0.3) { el.innerHTML = ''; return; }
    el.innerHTML = '<div class="banner-strip is-warning">Elevated drift detected across the platform (' +
      fmtPct(metrics.drift_score) + ' of tracked features) &mdash; <a href="/admin/monitoring#drift-section">Investigate &rarr;</a></div>';
  }

  function renderModelHealth(rows) {
    const body = document.getElementById('model-health-body');
    if (!rows.length) {
      body.innerHTML = '<tr><td colspan="5">' + UI.emptyState('No models deployed yet', 'Deployed models will show up here once available.') + '</td></tr>';
      return;
    }
    body.innerHTML = rows.map((r, idx) =>
      '<tr><td class="mono">' + UI.escapeHtml(r.name) + '</td><td><span class="chip-mono">' + UI.escapeHtml(r.task) + '</span></td><td class="text-secondary">' +
      UI.escapeHtml(r.model_type) + '</td><td>' + UI.statusBadge(r.status) + (r.is_active === false ? ' ' + UI.statusDot('Disabled', 'offline') : '') + '</td><td>' +
      '<button class="link-action" data-toggle-active="' + idx + '" type="button">' + (r.is_active === false ? 'Enable' : 'Disable') + '</button> ' +
      '<button class="link-action link-danger" data-delete-model="' + idx + '" type="button">Delete</button>' +
      '</td></tr>'
    ).join('');
    body.querySelectorAll('[data-toggle-active]').forEach(btn => {
      btn.addEventListener('click', () => toggleActive(overviewRows[parseInt(btn.dataset.toggleActive, 10)], btn));
    });
    body.querySelectorAll('[data-delete-model]').forEach(btn => {
      btn.addEventListener('click', () => confirmDeleteModel(overviewRows[parseInt(btn.dataset.deleteModel, 10)]));
    });
  }

  // Disable/Enable and Delete need an unscoped workspace API key, same as
  // the Model Registry page - prompted for once, lazily, cached for the
  // rest of this page's lifetime.
  function ensureApiKey() {
    if (managementApiKey) return Promise.resolve(managementApiKey);
    return new Promise((resolve) => {
      const overlay = UI.openModal({
        title: 'API key required',
        bodyHtml: `
          <p class="text-secondary" style="font-size:var(--text-sm);margin-bottom:var(--space-3)">An unscoped workspace API key is needed to manage models - see API Keys.</p>
          <div class="field"><label class="field-label" for="ov-api-key">API key</label><input class="input" type="password" id="ov-api-key" placeholder="aodp_your_admin_key"></div>
        `,
        footerHtml: `<button class="btn btn-ghost" id="ov-key-cancel" type="button">Cancel</button>
                     <button class="btn btn-primary" id="ov-key-save" type="button">Continue</button>`,
      });
      const finish = (value) => { UI.closeModal(); resolve(value); };
      overlay.querySelector('#ov-key-cancel').addEventListener('click', () => finish(null));
      const input = overlay.querySelector('#ov-api-key');
      const save = () => {
        const value = input.value.trim();
        if (!value) return;
        managementApiKey = value;
        finish(value);
      };
      overlay.querySelector('#ov-key-save').addEventListener('click', save);
      input.addEventListener('keydown', (e) => { if (e.key === 'Enter') save(); });
    });
  }

  async function toggleActive(row, btn) {
    const key = await ensureApiKey();
    if (!key) return;
    const newActive = !(row.is_active !== false);
    btn.disabled = true;
    try {
      const res = await fetch('/api/v1/deployment/' + row.id, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', 'X-API-Key': key },
        body: JSON.stringify({ is_active: newActive }),
      });
      const data = await res.json().catch(() => null);
      if (!res.ok) throw new Error((data && data.detail) || 'Could not update model');
      UI.toast(newActive ? 'Model enabled' : 'Model disabled', 'success');
      loadOverview();
    } catch (e) {
      UI.toast(e.message || 'Could not update model', 'danger');
      btn.disabled = false;
    }
  }

  async function confirmDeleteModel(row) {
    const key = await ensureApiKey();
    if (!key) return;
    const overlay = UI.openModal({
      title: 'Delete ' + row.name,
      bodyHtml: `
        <div class="alert alert-danger" style="margin-bottom:var(--space-3)">
          <div><div class="alert-title">This cannot be undone</div><div>This will remove the model and revoke all team access. Type the model name to confirm.</div></div>
        </div>
        <div class="field">
          <label class="field-label" for="ov-del-confirm-name">Model name</label>
          <input class="input" id="ov-del-confirm-name" placeholder="${UI.escapeHtml(row.name)}">
        </div>
        <div class="field-error" id="ov-del-confirm-error" role="alert"></div>
      `,
      footerHtml: `<button class="btn btn-ghost" id="ov-del-cancel" type="button">Cancel</button>
                   <button class="btn btn-danger" id="ov-del-confirm" type="button" disabled>Delete</button>`,
    });
    const input = overlay.querySelector('#ov-del-confirm-name');
    const confirmBtn = overlay.querySelector('#ov-del-confirm');
    const errorEl = overlay.querySelector('#ov-del-confirm-error');
    input.addEventListener('input', () => { confirmBtn.disabled = input.value !== row.name; });
    overlay.querySelector('#ov-del-cancel').addEventListener('click', UI.closeModal);
    confirmBtn.addEventListener('click', async () => {
      confirmBtn.disabled = true;
      confirmBtn.textContent = 'Deleting…';
      errorEl.textContent = '';
      try {
        const path = row.model_type === 'custom' ? '/api/v1/custom-model/' + row.id : '/api/v1/deployment/' + row.id;
        const res = await fetch(path, { method: 'DELETE', headers: { 'X-API-Key': key } });
        const data = await res.json().catch(() => null);
        if (!res.ok) throw new Error((data && data.detail) || 'Could not delete model');
        UI.closeModal();
        UI.toast('Model deleted', 'success');
        loadOverview();
      } catch (e) {
        errorEl.textContent = e.message || 'Could not delete model.';
        confirmBtn.disabled = false;
        confirmBtn.textContent = 'Delete';
      }
    });
  }

  // Compact table (Ticket / Filed / Severity), consistent with Model
  // health above. Severity renders as dot + text; the row itself carries
  // no colour.
  function renderRecentTickets(tickets) {
    const el = document.getElementById('recent-tickets');
    if (!tickets.length) {
      el.innerHTML = UI.emptyState('No tickets yet', 'Tickets filed by team members will appear here.');
      return;
    }
    const recent = tickets.slice(0, 5);
    el.innerHTML =
      '<div class="table-wrap"><table class="table" style="min-width:480px">' +
      '<thead><tr><th>Ticket</th><th>Filed</th><th>Severity</th></tr></thead><tbody>' +
      recent.map(t =>
        '<tr><td>' + UI.escapeHtml(t.title) + '</td>' +
        '<td class="text-muted">' + UI.timeAgo(t.filed_at) + '</td>' +
        '<td>' + UI.severityBadge(t.severity) + '</td></tr>'
      ).join('') +
      '</tbody></table></div>' +
      '<div style="margin-top:var(--space-3)"><a class="link-action" href="/admin/tickets-page">View all tickets &rarr;</a></div>';
  }
</script>"""

    ready = "initOverview(user);"

    html = (
        "<!DOCTYPE html>\n<html lang=\"en\">\n<head>\n<meta charset=\"UTF-8\">\n"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">\n"
        "<title>Overview - Vela Admin</title>\n" + ds_assets + "\n</head>\n<body>\n"
        + body
        + "\n" + _SCRIPTS + "\n" + script
        + _boot_script("/admin", "Overview", ready)
        + "\n</body>\n</html>"
    )
    return html


# =========================================================================
# Users - /admin/users-page
# =========================================================================

@router.get("/admin/users-page", response_class=HTMLResponse)
def admin_users_page():
    # Phase 2: migrated to the ds/* design system (see admin_overview_page /
    # admin_deployments_page / admin_models_page for the reference pattern).
    # ds/* bundle for this route only; every other admin page still uses
    # _ASSETS. Shared JS (_SCRIPTS) is theme-agnostic and unchanged.
    ds_assets = (
        '<link rel="stylesheet" href="/static/css/ds/tokens.css?v=ds5">\n'
        '<link rel="stylesheet" href="/static/css/ds/base.css?v=ds5">\n'
        '<link rel="stylesheet" href="/static/css/ds/primitives.css?v=ds5">\n'
        '<link rel="stylesheet" href="/static/css/ds/shell.css?v=ds7">'
    )

    body = """
<div id="page-content" hidden>
  <div class="page-max">
    <div class="page-header">
      <div>
        <h1 class="page-title">Users</h1>
        <div class="page-description">Every user account on the platform.</div>
      </div>
      <div class="page-actions">
        <button class="btn btn-secondary btn-sm" id="refresh-btn" type="button">Refresh</button>
        <button class="btn btn-primary btn-sm" id="new-user-btn" type="button">New user</button>
      </div>
    </div>

    <div class="toolbar">
      <span class="input-group" style="flex:1 1 220px">
        <svg class="input-icon" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5"><circle cx="7" cy="7" r="4.5"/><path d="m11 11 3 3"/></svg>
        <input class="input" id="users-filter" type="text" placeholder="Filter by username, name, role, team or status" autocomplete="off" style="flex:1;min-width:0">
      </span>
      <span class="toolbar-spacer"></span>
      <span class="text-muted" id="users-count" style="font-size:var(--text-xs);flex-shrink:0"></span>
    </div>
    <div class="table-wrap">
      <table class="table" style="min-width:720px">
        <thead>
          <tr><th>Username</th><th>Name</th><th>Role</th><th>Teams</th><th>Status</th><th>Created</th><th class="num">Actions</th></tr>
        </thead>
        <tbody id="users-body"></tbody>
      </table>
    </div>
  </div>

  <div class="slideover-overlay" id="new-user-panel" hidden>
  <div class="slideover" role="dialog" aria-modal="true" aria-labelledby="new-user-panel-title">
    <div class="slideover-header">
      <div class="slideover-title" id="new-user-panel-title">New user</div>
      <button class="btn btn-ghost btn-sm btn-icon" id="close-new-user-panel" type="button" aria-label="Close">&#10005;</button>
    </div>
    <div class="slideover-body">
      <form class="form" id="new-user-form" novalidate>
        <div class="field"><label class="field-label" for="nu-username">Username</label><input class="input" id="nu-username" required></div>
        <div class="field"><label class="field-label" for="nu-name">Full name</label><input class="input" id="nu-name" required></div>
        <div class="field"><label class="field-label" for="nu-password">Temporary password</label><input class="input" type="password" id="nu-password" required minlength="6"></div>
        <div class="checkbox-row" style="margin-bottom:var(--space-2)"><input type="checkbox" id="nu-admin"><label for="nu-admin">Grant admin access</label></div>
        <div class="checkbox-row" style="margin-bottom:var(--space-2)"><input type="checkbox" id="nu-force" checked><label for="nu-force">Require password change at first login</label></div>
        <div class="field-error" id="nu-error" role="alert"></div>
        <button class="btn btn-primary btn-block" type="submit" id="nu-submit">Create user</button>
      </form>
    </div>
  </div>
  </div>
</div>
<div id="loading-root" style="min-height:100vh;display:flex;align-items:center;justify-content:center;color:var(--text-muted);font-size:var(--text-sm)">Loading&hellip;</div>
"""

    script = """
<script>
  let currentUser = null;
  let cachedUsers = [];
  let cachedTeams = [];

  let newUserPanelReturnFocus = null;

  function initUsers(user) {
    currentUser = user;
    const refreshBtn = document.getElementById('refresh-btn');
    if (refreshBtn) refreshBtn.addEventListener('click', () => loadUsers());
    const filterInput = document.getElementById('users-filter');
    if (filterInput) filterInput.addEventListener('input', renderUsersTable);
    wireNewUserPanel();
    loadUsers();
  }

  async function loadUsers() {
    const body = document.getElementById('users-body');
    body.innerHTML = UI.skeletonRows(7, 4);
    try {
      const [users, teams] = await Promise.all([Api.get('/admin/users'), Api.get('/admin/teams')]);
      cachedUsers = users;
      cachedTeams = teams;
      renderUsersTable();
    } catch (e) {
      cachedUsers = [];
      body.innerHTML = '<tr><td colspan="7">' + UI.errorState(e.message, loadUsers) + '</td></tr>';
      const countEl = document.getElementById('users-count');
      if (countEl) countEl.textContent = '';
    }
  }

  function teamsForUser(userId) {
    const names = [];
    cachedTeams.forEach(t => {
      if ((t.members || []).some(m => m.user_id === userId)) names.push(t.name);
    });
    return names;
  }

  // Client-side only: filters the already-loaded cachedUsers. Row actions
  // are keyed by user id (data-deactivate="u.id" etc.), not array
  // position, so - unlike the Models registry filter - there's no index
  // to remap here; filtering never changes which user a button acts on.
  function renderUsersTable() {
    const body = document.getElementById('users-body');
    const countEl = document.getElementById('users-count');
    const q = (document.getElementById('users-filter').value || '').trim().toLowerCase();

    if (!cachedUsers.length) {
      body.innerHTML = '<tr><td colspan="7">' + UI.emptyState('No users yet', 'Create the first user to get started.') + '</td></tr>';
      if (countEl) countEl.textContent = '';
      return;
    }

    const rows = cachedUsers.filter(u => {
      if (!q) return true;
      const role = u.is_admin ? 'admin' : 'member';
      const status = u.is_active ? 'active' : 'inactive';
      const teams = teamsForUser(u.id).join(' ').toLowerCase();
      return (u.username || '').toLowerCase().includes(q)
        || (u.name || '').toLowerCase().includes(q)
        || role.includes(q)
        || status.includes(q)
        || teams.includes(q);
    });

    if (countEl) {
      countEl.textContent = q
        ? rows.length + ' of ' + cachedUsers.length
        : cachedUsers.length + (cachedUsers.length === 1 ? ' user' : ' users');
    }

    if (!rows.length) {
      body.innerHTML = '<tr><td colspan="7">' + UI.emptyState('No matches', 'No user matches that filter.') + '</td></tr>';
      return;
    }

    body.innerHTML = rows.map(renderUserRow).join('');

    body.querySelectorAll('[data-deactivate]').forEach(btn => {
      btn.addEventListener('click', () => confirmDeactivateUser(btn.dataset.deactivate, btn.dataset.username));
    });
    body.querySelectorAll('[data-reactivate]').forEach(btn => {
      btn.addEventListener('click', () => reactivateUser(btn.dataset.reactivate, btn.dataset.username));
    });
    body.querySelectorAll('[data-delete]').forEach(btn => {
      btn.addEventListener('click', () => confirmDeleteUser(btn.dataset.delete, btn.dataset.username));
    });
  }

  // Role and team both read as plain neutral labels - .badge carries no
  // colour variants in this system, colour is reserved for real status
  // (the Status column below).
  function renderUserRow(u) {
    const teams = teamsForUser(u.id);
    const teamBadges = teams.length ? teams.map(t => UI.badge(t, 'neutral')).join(' ') : '<span class="text-muted">—</span>';
    const isSelf = currentUser && u.id === currentUser.id;
    let action;
    if (isSelf) {
      action = '<span class="text-muted" style="font-size:var(--text-xs)">You</span>';
    } else {
      const toggleBtn = u.is_active
        ? '<button class="link-action link-danger" data-deactivate="' + u.id + '" data-username="' + UI.escapeHtml(u.username) + '" type="button">Deactivate</button>'
        : '<button class="link-action" data-reactivate="' + u.id + '" data-username="' + UI.escapeHtml(u.username) + '" type="button">Reactivate</button>';
      action = toggleBtn + ' <button class="link-action link-danger" data-delete="' + u.id + '" data-username="' + UI.escapeHtml(u.username) + '" type="button">Delete</button>';
    }
    return '<tr>' +
      '<td class="mono">' + UI.escapeHtml(u.username) + '</td>' +
      '<td>' + UI.escapeHtml(u.name) + '</td>' +
      '<td>' + UI.badge(u.is_admin ? 'Admin' : 'Member', 'neutral') + '</td>' +
      '<td>' + teamBadges + '</td>' +
      '<td>' + UI.statusBadge(u.is_active ? 'active' : 'inactive') + (u.force_password_change ? ' ' + UI.statusDot('Pending first login', 'warning') : '') + '</td>' +
      '<td class="text-secondary">' + UI.fmtDate(u.created_at) + '</td>' +
      '<td class="num"><span style="display:inline-flex;gap:var(--space-3);align-items:center;justify-content:flex-end;flex-wrap:wrap">' + action + '</span></td>' +
      '</tr>';
  }

  // Reversible, so a single DS-styled confirm modal (no type-to-confirm) -
  // replaces the native confirm() the legacy page used. The underlying
  // call is exactly the same PATCH .../deactivate as before.
  function confirmDeactivateUser(id, username) {
    const overlay = UI.openModal({
      title: 'Deactivate ' + username,
      bodyHtml: `
        <div class="alert alert-warning">
          <div><div class="alert-title">${UI.escapeHtml(username)} will be signed out</div>They won't be able to log in until reactivated &mdash; this can be undone at any time.</div></div>
        </div>
      `,
      footerHtml: `<button class="btn btn-ghost" id="deact-cancel" type="button">Cancel</button>
                   <button class="btn btn-danger" id="deact-confirm" type="button">Deactivate</button>`,
    });
    overlay.querySelector('#deact-cancel').addEventListener('click', UI.closeModal);
    const confirmBtn = overlay.querySelector('#deact-confirm');
    confirmBtn.addEventListener('click', async () => {
      confirmBtn.disabled = true;
      confirmBtn.textContent = 'Deactivating…';
      try {
        await Api.patch('/admin/users/' + id + '/deactivate');
        UI.closeModal();
        UI.toast(username + ' deactivated', 'success');
        loadUsers();
      } catch (e) {
        UI.toast(e.message || 'Could not deactivate user', 'danger');
        confirmBtn.disabled = false;
        confirmBtn.textContent = 'Deactivate';
      }
    });
  }

  async function reactivateUser(id, username) {
    try {
      await Api.patch('/admin/users/' + id + '/reactivate');
      UI.toast(username + ' reactivated', 'success');
      loadUsers();
    } catch (e) {
      UI.toast(e.message || 'Could not reactivate user', 'danger');
    }
  }

  function confirmDeleteUser(id, username) {
    const overlay = UI.openModal({
      title: 'Delete ' + username,
      bodyHtml: `
        <div class="alert alert-danger" style="margin-bottom:var(--space-3)">
          <div><div class="alert-title">This cannot be undone</div><div>This will permanently delete the user and all their data. Type the username to confirm.</div></div>
        </div>
        <div class="field">
          <label class="field-label" for="del-user-confirm-name">Username</label>
          <input class="input" id="del-user-confirm-name" placeholder="${UI.escapeHtml(username)}">
        </div>
        <div class="field-error" id="del-user-confirm-error" role="alert"></div>
      `,
      footerHtml: `<button class="btn btn-ghost" id="del-user-cancel" type="button">Cancel</button>
                   <button class="btn btn-danger" id="del-user-confirm" type="button" disabled>Delete</button>`,
    });
    const input = overlay.querySelector('#del-user-confirm-name');
    const confirmBtn = overlay.querySelector('#del-user-confirm');
    const errorEl = overlay.querySelector('#del-user-confirm-error');

    input.addEventListener('input', () => {
      confirmBtn.disabled = input.value !== username;
    });
    overlay.querySelector('#del-user-cancel').addEventListener('click', UI.closeModal);

    confirmBtn.addEventListener('click', async () => {
      confirmBtn.disabled = true;
      confirmBtn.textContent = 'Deleting…';
      errorEl.textContent = '';
      try {
        await Api.del('/admin/users/' + id);
        UI.closeModal();
        UI.toast(username + ' deleted', 'success');
        loadUsers();
      } catch (e) {
        errorEl.textContent = e.message || 'Could not delete user.';
        confirmBtn.disabled = false;
        confirmBtn.textContent = 'Delete';
      }
    });
  }

  // CREATION flow -> slide-over (matches the "Deploy model" pattern on
  // /admin/deployments); CONFIRMATION dialogs (deactivate, delete above)
  // stay as modals. Same form, same ids, same validation, same POST -
  // only the surface it lives in changed.
  function wireNewUserPanel() {
    const panel = document.getElementById('new-user-panel');
    const openBtn = document.getElementById('new-user-btn');
    const closeBtn = document.getElementById('close-new-user-panel');
    if (!panel || !openBtn) return;

    openBtn.addEventListener('click', () => {
      newUserPanelReturnFocus = document.activeElement;
      panel.hidden = false;
      document.addEventListener('keydown', newUserPanelKeydown);
      const first = document.getElementById('nu-username');
      if (first) first.focus();
    });
    closeBtn.addEventListener('click', closeNewUserPanel);
    panel.addEventListener('click', (e) => { if (e.target === panel) closeNewUserPanel(); });

    document.getElementById('new-user-form').addEventListener('submit', async (e) => {
      e.preventDefault();
      const errorEl = document.getElementById('nu-error');
      const submitBtn = document.getElementById('nu-submit');
      const username = document.getElementById('nu-username').value.trim();
      const name = document.getElementById('nu-name').value.trim();
      const password = document.getElementById('nu-password').value;
      const is_admin = document.getElementById('nu-admin').checked;
      const force_password_change = document.getElementById('nu-force').checked;
      if (!username || !name || password.length < 6) {
        errorEl.textContent = 'Fill in all fields - password needs at least 6 characters.';
        return;
      }
      submitBtn.disabled = true;
      submitBtn.textContent = 'Creating…';
      try {
        await Api.post('/admin/users', { username, name, password, is_admin, force_password_change });
        UI.toast('User ' + username + ' created', 'success');
        closeNewUserPanel();
        loadUsers();
      } catch (err) {
        errorEl.textContent = err.message || 'Could not create user.';
      } finally {
        submitBtn.disabled = false;
        submitBtn.textContent = 'Create user';
      }
    });
  }

  function closeNewUserPanel() {
    const panel = document.getElementById('new-user-panel');
    if (!panel || panel.hidden) return;
    panel.hidden = true;
    document.removeEventListener('keydown', newUserPanelKeydown);
    document.getElementById('new-user-form').reset();
    document.getElementById('nu-error').textContent = '';
    if (newUserPanelReturnFocus && document.contains(newUserPanelReturnFocus)) newUserPanelReturnFocus.focus();
    newUserPanelReturnFocus = null;
  }

  function newUserPanelKeydown(e) {
    if (e.key === 'Escape') { closeNewUserPanel(); return; }
    if (e.key !== 'Tab') return;
    const panel = document.getElementById('new-user-panel');
    const focusables = Array.from(panel.querySelectorAll(
      'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled])'
    )).filter(el => el.offsetParent !== null);
    if (!focusables.length) return;
    const first = focusables[0], last = focusables[focusables.length - 1];
    if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
    else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
  }
</script>"""

    ready = "initUsers(user);"

    html = (
        "<!DOCTYPE html>\n<html lang=\"en\">\n<head>\n<meta charset=\"UTF-8\">\n"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">\n"
        "<title>Users - Vela Admin</title>\n" + ds_assets + "\n</head>\n<body>\n"
        + body
        + "\n" + _SCRIPTS + "\n" + script
        + _boot_script("/admin/users-page", "Users", ready)
        + "\n</body>\n</html>"
    )
    return html


# =========================================================================
# Teams - /admin/teams-page
#
# Phase 2: migrated to the ds/* design system (see admin_users_page for
# the reference pattern - creation in a slide-over, confirmations as
# modals). Presentation only: every loader and CRUD call below (teams/
# users/deployments loads, add/remove member, grant/revoke model access,
# create team) is unchanged - only the surface it's wired through moved.
#
# The old page rendered one always-expanded card per team, each inlining
# a full members+models editor - fine for a handful of teams, not for
# many. That's now a compact table (one row per team) plus an on-screen
# "Manage" slide-over per team, opened on demand, holding exactly the
# same member/model editor. That's the focused, multi-part-form case
# slide-overs are for; it's just no longer rendered N times at once for N
# teams. No delete-team action: there is no DELETE /admin/teams/{id}
# endpoint to call, so one isn't invented here.
# =========================================================================

@router.get("/admin/teams-page", response_class=HTMLResponse)
def admin_teams_page():
    ds_assets = (
        '<link rel="stylesheet" href="/static/css/ds/tokens.css?v=ds5">\n'
        '<link rel="stylesheet" href="/static/css/ds/base.css?v=ds5">\n'
        '<link rel="stylesheet" href="/static/css/ds/primitives.css?v=ds5">\n'
        '<link rel="stylesheet" href="/static/css/ds/shell.css?v=ds7">'
    )

    body = """
<div id="page-content" hidden>
  <div class="page-max">
    <div class="page-header">
      <div>
        <h1 class="page-title">Teams</h1>
        <div class="page-description">Team membership and per-team model access.</div>
      </div>
      <div class="page-actions">
        <button class="btn btn-secondary btn-sm" id="refresh-btn" type="button">Refresh</button>
        <button class="btn btn-primary btn-sm" id="new-team-btn" type="button">New team</button>
      </div>
    </div>

    <div class="toolbar">
      <span class="input-group" style="flex:1 1 220px">
        <svg class="input-icon" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5"><circle cx="7" cy="7" r="4.5"/><path d="m11 11 3 3"/></svg>
        <input class="input" id="teams-filter" type="text" placeholder="Filter by name or description" autocomplete="off" style="flex:1;min-width:0">
      </span>
      <span class="toolbar-spacer"></span>
      <span class="text-muted" id="teams-count" style="font-size:var(--text-xs);flex-shrink:0"></span>
    </div>
    <div class="table-wrap">
      <table class="table" style="min-width:560px">
        <thead>
          <tr><th>Name</th><th>Description</th><th class="num">Members</th><th class="num">Models</th><th class="num">Actions</th></tr>
        </thead>
        <tbody id="teams-body"></tbody>
      </table>
    </div>
  </div>

  <div class="slideover-overlay" id="new-team-panel" hidden>
  <div class="slideover" role="dialog" aria-modal="true" aria-labelledby="new-team-panel-title">
    <div class="slideover-header">
      <div class="slideover-title" id="new-team-panel-title">New team</div>
      <button class="btn btn-ghost btn-sm btn-icon" id="close-new-team-panel" type="button" aria-label="Close">&#10005;</button>
    </div>
    <div class="slideover-body">
      <form class="form" id="new-team-form" novalidate>
        <div class="field"><label class="field-label" for="nt-name">Team name</label><input class="input" id="nt-name" required></div>
        <div class="field"><label class="field-label" for="nt-desc">Description (optional)</label><textarea class="textarea" id="nt-desc" rows="3"></textarea></div>
        <div class="field-error" id="nt-error" role="alert"></div>
        <button class="btn btn-primary btn-block" type="submit" id="nt-submit">Create team</button>
      </form>
    </div>
  </div>
  </div>

  <div class="slideover-overlay" id="manage-team-panel" hidden>
  <div class="slideover" role="dialog" aria-modal="true" aria-labelledby="manage-team-panel-title">
    <div class="slideover-header">
      <div class="slideover-title" id="manage-team-panel-title">Manage team</div>
      <button class="btn btn-ghost btn-sm btn-icon" id="close-manage-team-panel" type="button" aria-label="Close">&#10005;</button>
    </div>
    <div class="slideover-body" id="manage-team-body"></div>
  </div>
  </div>
</div>
<div id="loading-root" style="min-height:100vh;display:flex;align-items:center;justify-content:center;color:var(--text-muted);font-size:var(--text-sm)">Loading&hellip;</div>
"""

    script = """
<script>
  let cachedUsers = [];
  let cachedTeams = [];
  let cachedDeployments = [];
  let workspaceId = null;
  let currentManageTeamId = null;

  async function ensureWorkspace() {
    if (workspaceId) return workspaceId;
    const workspaces = await Api.get('/workspaces');
    if (workspaces.length) {
      workspaceId = workspaces[0].id;
    } else {
      const ws = await Api.post('/workspaces', { name: 'Default Workspace', description: 'Bootstrapped automatically for team creation' });
      workspaceId = ws.id;
    }
    return workspaceId;
  }

  function initTeams() {
    const refreshBtn = document.getElementById('refresh-btn');
    if (refreshBtn) refreshBtn.addEventListener('click', () => loadTeams());
    const filterInput = document.getElementById('teams-filter');
    if (filterInput) filterInput.addEventListener('input', renderTeamsTable);
    wireNewTeamPanel();
    wireManageTeamPanel();
    loadTeams();
  }

  async function loadTeams() {
    const body = document.getElementById('teams-body');
    body.innerHTML = UI.skeletonRows(5, 4);
    try {
      const [teams, users, deployments] = await Promise.all([
        Api.get('/admin/teams'), Api.get('/admin/users'), Api.get('/admin/deployment-registry')
      ]);
      cachedTeams = teams;
      cachedUsers = users;
      cachedDeployments = deployments;
      renderTeamsTable();
      // Keep an open Manage panel showing live data after a mutation -
      // add/remove member and grant/revoke access all call loadTeams()
      // on success, and the panel would otherwise still show the
      // pre-mutation list until closed and reopened.
      if (currentManageTeamId != null) renderManagePanelBody(currentManageTeamId);
    } catch (e) {
      cachedTeams = [];
      body.innerHTML = '<tr><td colspan="5">' + UI.errorState(e.message, loadTeams) + '</td></tr>';
      const countEl = document.getElementById('teams-count');
      if (countEl) countEl.textContent = '';
    }
  }

  // Client-side only: filters the already-loaded cachedTeams, same
  // pattern as the Users registry filter.
  function renderTeamsTable() {
    const body = document.getElementById('teams-body');
    const countEl = document.getElementById('teams-count');
    const q = (document.getElementById('teams-filter').value || '').trim().toLowerCase();

    if (!cachedTeams.length) {
      body.innerHTML = '<tr><td colspan="5">' + UI.emptyState('No teams yet', 'Create a team to start assigning members and model access.') + '</td></tr>';
      if (countEl) countEl.textContent = '';
      return;
    }

    const rows = cachedTeams.filter(t => {
      if (!q) return true;
      return (t.name || '').toLowerCase().includes(q) || (t.description || '').toLowerCase().includes(q);
    });

    if (countEl) {
      countEl.textContent = q
        ? rows.length + ' of ' + cachedTeams.length
        : cachedTeams.length + (cachedTeams.length === 1 ? ' team' : ' teams');
    }

    if (!rows.length) {
      body.innerHTML = '<tr><td colspan="5">' + UI.emptyState('No matches', 'No team matches that filter.') + '</td></tr>';
      return;
    }

    body.innerHTML = rows.map(renderTeamRow).join('');
    body.querySelectorAll('[data-manage-team]').forEach(btn => {
      btn.addEventListener('click', () => openManageTeamPanel(btn.dataset.manageTeam));
    });
  }

  // Member/model counts are plain facts, not exceptions - neutral, same
  // as the rest of this table. Role (member/lead) inside the Manage
  // panel is the only place this page labels anything, and that stays a
  // neutral badge too (see renderManagePanelBody) - color is reserved
  // for real status elsewhere in this system, not for identity labels.
  function renderTeamRow(t) {
    const memberCount = (t.members || []).length;
    const modelCount = (t.permissions || []).length;
    return '<tr>' +
      '<td>' + UI.escapeHtml(t.name) + '</td>' +
      '<td class="text-secondary">' + (t.description ? UI.escapeHtml(t.description) : '<span class="text-muted">—</span>') + '</td>' +
      '<td class="num">' + memberCount + '</td>' +
      '<td class="num">' + modelCount + '</td>' +
      '<td class="num"><button class="link-action" data-manage-team="' + t.id + '" type="button">Manage</button></td>' +
      '</tr>';
  }

  // ================================================================
  // Manage team slide-over - members + model access for one team,
  // opened on demand. One scrolling panel (slideover-body already
  // scrolls) rather than tabbed; if members+models ever gets too tall
  // in practice, tabbing it is a follow-up, not a pre-optimization.
  // ================================================================

  function renderManagePanelBody(teamId) {
    const t = cachedTeams.find(x => String(x.id) === String(teamId));
    const titleEl = document.getElementById('manage-team-panel-title');
    const body = document.getElementById('manage-team-body');
    if (!t) { if (titleEl) titleEl.textContent = 'Manage team'; body.innerHTML = ''; return; }
    if (titleEl) titleEl.textContent = t.name;

    const memberIds = new Set((t.members || []).map(m => m.user_id));
    const memberCount = (t.members || []).length;
    const memberRows = memberCount
      ? t.members.map(m => {
          const label = m.name || m.email || ('User #' + m.user_id);
          return '<div style="display:flex;justify-content:space-between;align-items:center;padding:.35rem 0;border-bottom:var(--border-width) solid var(--border-subtle)">' +
            '<span style="font-size:var(--text-sm)">' + UI.escapeHtml(label) + (m.role === 'lead' ? ' ' + UI.badge('Lead', 'neutral') : '') + '</span>' +
            '<button class="link-action link-danger" data-remove-member="' + t.id + ':' + m.user_id + '" data-member-name="' + UI.escapeHtml(label) + '" type="button">Remove</button>' +
            '</div>';
        }).join('')
      : '<div class="text-muted" style="font-size:var(--text-sm);padding:.35rem 0">No members yet</div>';

    const availableUsers = cachedUsers.filter(u => u.is_active && !memberIds.has(u.id));
    const userOptions = availableUsers.map(u => '<option value="' + u.id + '">' + UI.escapeHtml(u.name) + ' (' + UI.escapeHtml(u.username) + ')</option>').join('');
    const addMemberRow = availableUsers.length
      ? '<div style="display:flex;gap:.5rem;margin-top:var(--space-2);flex-wrap:wrap">' +
        '<select class="select" id="mt-add-user" style="flex:2;min-width:120px">' + userOptions + '</select>' +
        '<select class="select" id="mt-add-role" style="flex:1;min-width:90px"><option value="member">Member</option><option value="lead">Lead</option></select>' +
        '<button class="btn btn-secondary btn-sm" id="mt-add-member" type="button">Add</button>' +
        '</div>'
      : '';

    const perms = t.permissions || [];
    const modelCount = perms.length;
    const permRows = modelCount
      ? perms.map(p => {
          const label = p.model_name || p.deployment_name || ('Deployment #' + p.deployment_id);
          return '<div style="display:flex;justify-content:space-between;align-items:center;padding:.35rem 0;border-bottom:var(--border-width) solid var(--border-subtle)">' +
            '<span style="font-size:var(--text-sm)">' + UI.escapeHtml(label) +
            '<span class="text-muted" style="font-size:var(--text-xs)">' + (p.can_predict ? ' &middot; predict' : '') + (p.can_view_metrics ? ' &middot; view metrics' : '') + '</span></span>' +
            '<button class="link-action link-danger" data-revoke-perm="' + t.id + ':' + p.deployment_id + '" data-model-name="' + UI.escapeHtml(label) + '" type="button">Revoke</button>' +
            '</div>';
        }).join('')
      : '<div class="text-muted" style="font-size:var(--text-sm);padding:.35rem 0">No model access granted yet</div>';

    // deployment_id is a real FK into the deployments table - GET
    // /deployments (k8s-live) doesn't carry that id at all, so the "add
    // model" dropdown is sourced from /admin/deployment-registry instead
    // (real Deployment rows only). Already-granted ones are filtered out.
    const grantedIds = new Set(perms.map(p => p.deployment_id));
    const availableDeployments = cachedDeployments.filter(d => !grantedIds.has(d.id));
    const deploymentOptions = availableDeployments.map(d =>
      '<option value="' + d.id + '">' + UI.escapeHtml(d.model_name || d.name) + ' (' + UI.escapeHtml(d.task_type) + ')</option>'
    ).join('');

    let addModelRow;
    if (availableDeployments.length) {
      addModelRow =
        '<div style="display:flex;gap:.5rem;margin-top:var(--space-2);flex-wrap:wrap;align-items:center">' +
        '<select class="select" id="mt-add-deployment" style="flex:2;min-width:160px">' + deploymentOptions + '</select>' +
        '<label class="checkbox-row"><input type="checkbox" id="mt-can-predict" checked> Can predict</label>' +
        '<button class="btn btn-secondary btn-sm" id="mt-grant-access" type="button">Add</button>' +
        '</div>';
    } else if (cachedDeployments.length) {
      addModelRow = '<div class="text-muted" style="font-size:var(--text-xs);margin-top:var(--space-2)">All available models already granted</div>';
    } else {
      addModelRow = '<div class="text-muted" style="font-size:var(--text-xs);margin-top:var(--space-2)">No models deployed yet</div>';
    }

    body.innerHTML =
      (t.description ? '<p class="text-secondary" style="font-size:var(--text-sm);margin-bottom:var(--space-4)">' + UI.escapeHtml(t.description) + '</p>' : '') +
      '<div class="section-label" style="margin-top:0">Members &middot; ' + memberCount + '</div>' +
      memberRows + addMemberRow +
      '<div class="section-label">Models &middot; ' + modelCount + '</div>' +
      permRows + addModelRow;

    body.querySelectorAll('[data-remove-member]').forEach(btn => {
      btn.addEventListener('click', () => {
        const [tId, userId] = btn.dataset.removeMember.split(':');
        confirmRemoveMember(tId, userId, btn.dataset.memberName);
      });
    });
    const addMemberBtn = document.getElementById('mt-add-member');
    if (addMemberBtn) addMemberBtn.addEventListener('click', () => {
      const userSel = document.getElementById('mt-add-user');
      const roleSel = document.getElementById('mt-add-role');
      if (userSel && userSel.value) addMember(t.id, userSel.value, roleSel.value);
    });
    body.querySelectorAll('[data-revoke-perm]').forEach(btn => {
      btn.addEventListener('click', () => {
        const [tId, deploymentId] = btn.dataset.revokePerm.split(':');
        confirmRevokeAccess(tId, deploymentId, btn.dataset.modelName);
      });
    });
    const grantBtn = document.getElementById('mt-grant-access');
    if (grantBtn) grantBtn.addEventListener('click', () => {
      const depSel = document.getElementById('mt-add-deployment');
      const predictChk = document.getElementById('mt-can-predict');
      if (depSel && depSel.value) grantAccess(t.id, depSel.value, predictChk.checked, false);
    });
  }

  function openManageTeamPanel(teamId) {
    currentManageTeamId = String(teamId);
    renderManagePanelBody(currentManageTeamId);
    openSlideover('manage-team-panel', '#close-manage-team-panel', closeManageTeamPanel);
  }

  function closeManageTeamPanel() {
    closeSlideoverChrome('manage-team-panel');
    currentManageTeamId = null;
  }

  function wireManageTeamPanel() {
    const panel = document.getElementById('manage-team-panel');
    const closeBtn = document.getElementById('close-manage-team-panel');
    if (!panel) return;
    closeBtn.addEventListener('click', closeManageTeamPanel);
    panel.addEventListener('click', (e) => { if (e.target === panel) closeManageTeamPanel(); });
  }

  async function grantAccess(teamId, deploymentId, canPredict, canViewMetrics) {
    try {
      await Api.post('/teams/' + teamId + '/permissions', {
        deployment_id: parseInt(deploymentId, 10),
        can_predict: canPredict,
        can_view_metrics: canViewMetrics,
      });
      UI.toast('Model access granted', 'success');
      loadTeams();
    } catch (e) {
      UI.toast(e.message || 'Could not grant access', 'danger');
    }
  }

  // Reversible (access can be granted right back), so a single DS-styled
  // confirm modal - same treatment as Deactivate User, not the
  // type-to-confirm Delete User gets - replacing the native confirm()
  // the legacy page used. Underlying call unchanged.
  function confirmRevokeAccess(teamId, deploymentId, modelName) {
    const overlay = UI.openModal({
      title: 'Revoke access to ' + (modelName || 'this model'),
      bodyHtml: `
        <div class="alert alert-warning">
          <div><div class="alert-title">This team will lose access</div>Access can be granted again at any time.</div></div>
        </div>
      `,
      footerHtml: `<button class="btn btn-ghost" id="revoke-cancel" type="button">Cancel</button>
                   <button class="btn btn-danger" id="revoke-confirm" type="button">Revoke</button>`,
    });
    overlay.querySelector('#revoke-cancel').addEventListener('click', UI.closeModal);
    const confirmBtn = overlay.querySelector('#revoke-confirm');
    confirmBtn.addEventListener('click', async () => {
      confirmBtn.disabled = true;
      confirmBtn.textContent = 'Revoking…';
      try {
        await Api.del('/teams/' + teamId + '/permissions/' + deploymentId);
        UI.closeModal();
        UI.toast('Access revoked', 'success');
        loadTeams();
      } catch (e) {
        UI.toast(e.message || 'Could not revoke access', 'danger');
        confirmBtn.disabled = false;
        confirmBtn.textContent = 'Revoke';
      }
    });
  }

  async function addMember(teamId, userId, role) {
    try {
      await Api.post('/admin/teams/' + teamId + '/users/' + userId + '?role=' + encodeURIComponent(role));
      UI.toast('Member added', 'success');
      loadTeams();
    } catch (e) {
      UI.toast(e.message || 'Could not add member', 'danger');
    }
  }

  // Same reversible-action treatment as confirmRevokeAccess above -
  // replaces the native confirm() the legacy page used. Underlying call
  // unchanged.
  function confirmRemoveMember(teamId, userId, memberName) {
    const overlay = UI.openModal({
      title: 'Remove ' + (memberName || 'member'),
      bodyHtml: `
        <div class="alert alert-warning">
          <div><div class="alert-title">${UI.escapeHtml(memberName || 'This member')} will lose access</div>They can be re-added to the team at any time.</div></div>
        </div>
      `,
      footerHtml: `<button class="btn btn-ghost" id="rm-member-cancel" type="button">Cancel</button>
                   <button class="btn btn-danger" id="rm-member-confirm" type="button">Remove</button>`,
    });
    overlay.querySelector('#rm-member-cancel').addEventListener('click', UI.closeModal);
    const confirmBtn = overlay.querySelector('#rm-member-confirm');
    confirmBtn.addEventListener('click', async () => {
      confirmBtn.disabled = true;
      confirmBtn.textContent = 'Removing…';
      try {
        await Api.del('/admin/teams/' + teamId + '/users/' + userId);
        UI.closeModal();
        UI.toast('Member removed', 'success');
        loadTeams();
      } catch (e) {
        UI.toast(e.message || 'Could not remove member', 'danger');
        confirmBtn.disabled = false;
        confirmBtn.textContent = 'Remove';
      }
    });
  }

  // ================================================================
  // Shared slide-over chrome (open/close/focus-trap) - both New team and
  // Manage team use this; each panel still owns its own open/close
  // wrapper for its own cleanup (form reset, currentManageTeamId).
  // ================================================================

  const slideoverState = {};

  function openSlideover(id, focusSelector, onClose) {
    const panel = document.getElementById(id);
    if (!panel) return;
    const state = { returnFocus: document.activeElement };
    state.keydownHandler = (e) => {
      if (e.key === 'Escape') { onClose(); return; }
      if (e.key !== 'Tab') return;
      const focusables = Array.from(panel.querySelectorAll(
        'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled])'
      )).filter(el => el.offsetParent !== null);
      if (!focusables.length) return;
      const first = focusables[0], last = focusables[focusables.length - 1];
      if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
      else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
    };
    slideoverState[id] = state;
    panel.hidden = false;
    document.addEventListener('keydown', state.keydownHandler);
    const first = focusSelector ? panel.querySelector(focusSelector) : null;
    if (first) first.focus();
  }

  function closeSlideoverChrome(id) {
    const panel = document.getElementById(id);
    const state = slideoverState[id];
    if (!panel || panel.hidden) return;
    panel.hidden = true;
    if (state && state.keydownHandler) document.removeEventListener('keydown', state.keydownHandler);
    if (state && state.returnFocus && document.contains(state.returnFocus)) state.returnFocus.focus();
    delete slideoverState[id];
  }

  // CREATION flow -> slide-over (matches the New user pattern);
  // CONFIRMATION dialogs (revoke access, remove member above, plus
  // Users' deactivate/delete) stay as modals. Same form, same ids, same
  // validation, same POST - only the surface it lives in changed (this
  // used to be a modal).
  function wireNewTeamPanel() {
    const panel = document.getElementById('new-team-panel');
    const openBtn = document.getElementById('new-team-btn');
    const closeBtn = document.getElementById('close-new-team-panel');
    if (!panel || !openBtn) return;

    openBtn.addEventListener('click', () => openSlideover('new-team-panel', '#nt-name', closeNewTeamPanel));
    closeBtn.addEventListener('click', closeNewTeamPanel);
    panel.addEventListener('click', (e) => { if (e.target === panel) closeNewTeamPanel(); });

    document.getElementById('new-team-form').addEventListener('submit', async (e) => {
      e.preventDefault();
      const errorEl = document.getElementById('nt-error');
      const submitBtn = document.getElementById('nt-submit');
      const name = document.getElementById('nt-name').value.trim();
      const description = document.getElementById('nt-desc').value.trim();
      if (!name) { errorEl.textContent = 'Team name is required.'; return; }
      submitBtn.disabled = true;
      submitBtn.textContent = 'Creating…';
      errorEl.textContent = '';
      try {
        const wsId = await ensureWorkspace();
        const params = new URLSearchParams({ name, description, workspace_id: wsId });
        await Api.post('/admin/teams?' + params.toString());
        UI.toast('Team ' + name + ' created', 'success');
        closeNewTeamPanel();
        loadTeams();
      } catch (err) {
        errorEl.textContent = err.message || 'Could not create team.';
      } finally {
        submitBtn.disabled = false;
        submitBtn.textContent = 'Create team';
      }
    });
  }

  function closeNewTeamPanel() {
    closeSlideoverChrome('new-team-panel');
    document.getElementById('new-team-form').reset();
    document.getElementById('nt-error').textContent = '';
  }
</script>"""

    ready = "initTeams();"

    html = (
        "<!DOCTYPE html>\n<html lang=\"en\">\n<head>\n<meta charset=\"UTF-8\">\n"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">\n"
        "<title>Teams - Vela Admin</title>\n" + ds_assets + "\n</head>\n<body>\n"
        + body
        + "\n" + _SCRIPTS + "\n" + script
        + _boot_script("/admin/teams-page", "Teams", ready)
        + "\n</body>\n</html>"
    )
    return html


# =========================================================================
# Tickets - /admin/tickets-page
# =========================================================================

@router.get("/admin/tickets-page", response_class=HTMLResponse)
def admin_tickets_page():
    ds_assets = (
        '<link rel="stylesheet" href="/static/css/ds/tokens.css?v=ds5">\n'
        '<link rel="stylesheet" href="/static/css/ds/base.css?v=ds5">\n'
        '<link rel="stylesheet" href="/static/css/ds/primitives.css?v=ds5">\n'
        '<link rel="stylesheet" href="/static/css/ds/shell.css?v=ds7">'
    )

    body = """
<div id="page-content" hidden>
  <div class="page-max">
    <div class="page-header">
      <div>
        <h1 class="page-title">Tickets</h1>
        <div class="page-description">Model risk and incident tickets filed by teams.</div>
      </div>
      <div class="page-actions">
        <button class="btn btn-secondary btn-sm" id="refresh-btn" type="button">Refresh</button>
      </div>
    </div>

    <div class="toolbar">
      <span class="input-group" style="flex:1 1 200px">
        <svg class="input-icon" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5"><circle cx="7" cy="7" r="4.5"/><path d="m11 11 3 3"/></svg>
        <input class="input" id="tickets-filter" type="text" placeholder="Filter by title, model or team" autocomplete="off" style="flex:1;min-width:0">
      </span>
      <select class="select" id="tickets-status-filter" aria-label="Filter by status">
        <option value="">All statuses</option>
        <option value="open">Open</option>
        <option value="investigating">Investigating</option>
        <option value="resolved">Resolved</option>
        <option value="closed">Closed</option>
      </select>
      <select class="select" id="tickets-severity-filter" aria-label="Filter by severity">
        <option value="">All severities</option>
        <option value="critical">Critical</option>
        <option value="high">High</option>
        <option value="medium">Medium</option>
        <option value="low">Low</option>
      </select>
      <select class="select" id="tickets-model-filter" aria-label="Filter by model">
        <option value="">All models</option>
      </select>
      <span class="toolbar-spacer"></span>
      <span class="text-muted" id="tickets-count" style="font-size:var(--text-xs);flex-shrink:0"></span>
    </div>
    <div class="table-wrap">
      <table class="table" style="min-width:760px">
        <thead>
          <tr><th>Title</th><th>Type</th><th>Severity</th><th>Status</th><th>Model</th><th>Team</th><th>Filed by</th><th>Filed</th><th></th></tr>
        </thead>
        <tbody id="tickets-body"></tbody>
      </table>
    </div>
  </div>
</div>
<div id="loading-root" style="min-height:100vh;display:flex;align-items:center;justify-content:center;color:var(--text-muted);font-size:var(--text-sm)">Loading&hellip;</div>
"""

    script = """
<script>
  // Severity is this screen's primary signal, so it gets its own local
  // dot mapping rather than the shared UI.severityBadge - that helper
  // also backs the member ticket pages and the admin overview widget,
  // and this screen's spec (critical/high colored, medium/low neutral)
  // is deliberately louder than theirs. Status stays on UI.statusBadge
  // as-is (open=info, investigating=warning, resolved=running,
  // closed=offline already reads as the right dot+text hierarchy).
  const TICKET_SEVERITY_VARIANT = { critical: 'error', high: 'warning', medium: 'neutral', low: 'neutral' };
  function ticketSeverityDot(sev) {
    const s = String(sev || 'medium').toLowerCase();
    return UI.statusDot(s.charAt(0).toUpperCase() + s.slice(1), TICKET_SEVERITY_VARIANT[s] || 'neutral');
  }

  let allTickets = [];

  function initTickets() {
    const refreshBtn = document.getElementById('refresh-btn');
    if (refreshBtn) refreshBtn.addEventListener('click', () => loadTickets());
    document.getElementById('tickets-filter').addEventListener('input', renderTickets);
    document.getElementById('tickets-status-filter').addEventListener('change', renderTickets);
    document.getElementById('tickets-severity-filter').addEventListener('change', renderTickets);
    document.getElementById('tickets-model-filter').addEventListener('change', renderTickets);
    loadTickets();
  }

  async function loadTickets() {
    const body = document.getElementById('tickets-body');
    body.innerHTML = UI.skeletonRows(9, 6);
    try {
      allTickets = await Api.get('/admin/tickets');
      renderModelFilterOptions();
      renderTickets();
    } catch (e) {
      allTickets = [];
      body.innerHTML = '<tr><td colspan="9">' + UI.errorState(e.message, loadTickets) + '</td></tr>';
      const countEl = document.getElementById('tickets-count');
      if (countEl) countEl.textContent = '';
    }
  }

  // Model options are data-driven (whatever's actually been ticketed
  // against), rebuilt on every load but keeping the current selection
  // if it's still one of the options.
  function renderModelFilterOptions() {
    const sel = document.getElementById('tickets-model-filter');
    const current = sel.value;
    const names = Array.from(new Set(allTickets.map(t => t.model_name || t.deployment_name).filter(Boolean))).sort();
    sel.innerHTML = '<option value="">All models</option>' + names.map(n => '<option value="' + UI.escapeHtml(n) + '">' + UI.escapeHtml(n) + '</option>').join('');
    if (names.includes(current)) sel.value = current;
  }

  // Client-side only, same pattern as the other migrated tables: one
  // cached load, filtered in place by the text query plus the three
  // dropdowns.
  function renderTickets() {
    const body = document.getElementById('tickets-body');
    const countEl = document.getElementById('tickets-count');
    const q = (document.getElementById('tickets-filter').value || '').trim().toLowerCase();
    const status = document.getElementById('tickets-status-filter').value;
    const severity = document.getElementById('tickets-severity-filter').value;
    const model = document.getElementById('tickets-model-filter').value;

    if (!allTickets.length) {
      body.innerHTML = '<tr><td colspan="9">' + UI.emptyState('No tickets yet', 'Tickets filed by teams will show up here.') + '</td></tr>';
      if (countEl) countEl.textContent = '';
      return;
    }

    const rows = allTickets.filter(t => {
      if (status && t.status !== status) return false;
      if (severity && String(t.severity).toLowerCase() !== severity) return false;
      if (model && (t.model_name || t.deployment_name) !== model) return false;
      if (!q) return true;
      const name = t.model_name || t.deployment_name || '';
      return (t.title || '').toLowerCase().includes(q)
        || name.toLowerCase().includes(q)
        || (t.team_name || '').toLowerCase().includes(q);
    });

    if (countEl) {
      countEl.textContent = (q || status || severity || model)
        ? rows.length + ' of ' + allTickets.length
        : allTickets.length + (allTickets.length === 1 ? ' ticket' : ' tickets');
    }

    if (!rows.length) {
      body.innerHTML = '<tr><td colspan="9">' + UI.emptyState('No matches', 'No ticket matches these filters.') + '</td></tr>';
      return;
    }

    body.innerHTML = rows.map(t =>
      '<tr class="is-interactive" data-open-ticket="' + t.id + '">' +
      '<td style="max-width:260px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">' + UI.escapeHtml(t.title) + '</td>' +
      '<td>' + UI.badge(t.ticket_type, 'neutral') + '</td>' +
      '<td>' + ticketSeverityDot(t.severity) + '</td>' +
      '<td>' + UI.statusBadge(t.status) + '</td>' +
      '<td class="text-secondary">' + UI.escapeHtml(t.model_name || t.deployment_name || '—') + '</td>' +
      '<td class="text-secondary">' + UI.escapeHtml(t.team_name || '—') + '</td>' +
      '<td class="text-secondary">' + UI.escapeHtml(t.filed_by_name) + '</td>' +
      '<td class="text-secondary">' + UI.timeAgo(t.filed_at) + '</td>' +
      '<td><button class="btn btn-ghost btn-sm" data-open-ticket-btn="' + t.id + '" type="button">View</button></td>' +
      '</tr>'
    ).join('');
    body.querySelectorAll('[data-open-ticket]').forEach(row => {
      row.addEventListener('click', () => openTicket(row.dataset.openTicket));
    });
  }

  function openTicket(id) {
    const t = allTickets.find(x => String(x.id) === String(id));
    if (!t) return;
    const overlay = UI.openModal({
      title: t.title,
      bodyHtml: `
        <div style="margin-bottom:.75rem;display:flex;gap:.5rem;flex-wrap:wrap">${ticketSeverityDot(t.severity)}${UI.statusBadge(t.status)}${UI.badge(t.ticket_type, 'neutral')}</div>
        <div class="text-secondary" style="font-size:var(--text-sm);white-space:pre-wrap;margin-bottom:.75rem">${UI.escapeHtml(t.description)}</div>
        ${t.evidence ? '<div class="section-label">Evidence</div><div class="text-secondary" style="font-size:var(--text-xs);white-space:pre-wrap;margin-bottom:.75rem">' + UI.escapeHtml(t.evidence) + '</div>' : ''}
        <div class="text-muted" style="font-size:var(--text-xs);margin-bottom:1rem">
          Filed by ${UI.escapeHtml(t.filed_by_name)} (${UI.escapeHtml(t.filed_by_username)}) &middot; ${UI.fmtDate(t.filed_at)}
          ${t.model_name ? ' &middot; model: ' + UI.escapeHtml(t.model_name) : ''}
          ${t.team_name ? ' &middot; team: ' + UI.escapeHtml(t.team_name) : ''}
        </div>
        <form id="ticket-form" novalidate>
          <div class="field">
            <label class="field-label" for="tk-status">Status</label>
            <select class="select" id="tk-status">
              <option value="open"${t.status === 'open' ? ' selected' : ''}>Open</option>
              <option value="investigating"${t.status === 'investigating' ? ' selected' : ''}>Investigating</option>
              <option value="resolved"${t.status === 'resolved' ? ' selected' : ''}>Resolved</option>
              <option value="closed"${t.status === 'closed' ? ' selected' : ''}>Closed</option>
            </select>
          </div>
          <div class="field">
            <label class="field-label" for="tk-note">Resolution note</label>
            <textarea class="textarea" id="tk-note" rows="3">${UI.escapeHtml(t.resolution_note || '')}</textarea>
            <div class="field-hint">Saved when status is set to Resolved or Closed.</div>
          </div>
          <div class="field-error" id="tk-error" role="alert"></div>
        </form>`,
      footerHtml: `<button class="btn btn-ghost" id="tk-cancel" type="button">Close</button>
                   <button class="btn btn-primary" id="tk-submit" type="submit" form="ticket-form">Save</button>`,
    });
    overlay.querySelector('#tk-cancel').addEventListener('click', UI.closeModal);
    overlay.querySelector('#ticket-form').addEventListener('submit', async (e) => {
      e.preventDefault();
      const submitBtn = overlay.querySelector('#tk-submit');
      const status = overlay.querySelector('#tk-status').value;
      const resolution_note = overlay.querySelector('#tk-note').value;
      const errorEl = overlay.querySelector('#tk-error');
      errorEl.textContent = '';
      submitBtn.disabled = true;
      submitBtn.textContent = 'Saving…';
      try {
        await Api.patch('/admin/tickets/' + t.id, { status, resolution_note });
        UI.toast('Ticket updated', 'success');
        UI.closeModal();
        loadTickets();
      } catch (err) {
        errorEl.textContent = err.message || 'Could not update ticket.';
        submitBtn.disabled = false;
        submitBtn.textContent = 'Save';
      }
    });
  }
</script>"""

    ready = "initTickets();"

    html = (
        "<!DOCTYPE html>\n<html lang=\"en\">\n<head>\n<meta charset=\"UTF-8\">\n"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">\n"
        "<title>Tickets - Vela Admin</title>\n" + ds_assets + "\n</head>\n<body>\n"
        + body
        + "\n" + _SCRIPTS + "\n" + script
        + _boot_script("/admin/tickets-page", "Tickets", ready)
        + "\n</body>\n</html>"
    )
    return html


# =========================================================================
# Monitoring - /admin/monitoring
# =========================================================================

@router.get("/admin/monitoring", response_class=HTMLResponse)
def admin_monitoring_page():
    ready = "Monitoring.start({role: 'admin'});"

    html = (
        "<!DOCTYPE html>\n<html lang=\"en\">\n<head>\n<meta charset=\"UTF-8\">\n"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">\n"
        "<title>Model Health - Vela Admin</title>\n" + DS_ASSETS + "\n" + CHART_JS_CDN + "\n" + MONITORING_CSS + "\n</head>\n<body>\n"
        + MONITORING_BODY
        + "\n" + _SCRIPTS + "\n" + MONITORING_SCRIPTS_EXTRA
        + _boot_script("/admin/monitoring", "Model Health", ready)
        + "\n</body>\n</html>"
    )
    return html


# =========================================================================
# Drift - folded into /admin/monitoring's #drift-section (see
# _page_fragments.py). This route is kept only as a redirect so old links
# and bookmarks to the former standalone Drift page don't 404.
# =========================================================================

@router.get("/admin/drift")
def admin_drift_page():
    return RedirectResponse(url="/admin/monitoring#drift-section", status_code=302)


# =========================================================================
# Remediation - /admin/remediation (spec §15 "Automated remediation")
#
# Phase 2: migrated to the ds/* design system (see admin_teams_page for
# the reference pattern - creation in a slide-over, confirmations as
# modals, shared openSlideover/closeSlideoverChrome helper). Presentation
# only: every loader and the create/test calls below are unchanged.
#
# The four backing endpoints (/api/v1/remediations, /api/v1/remediations/
# {workspace_id}, /api/v1/remediation-logs/{workspace_id}, /api/v1/
# remediations/{id}/test) now accept the admin's own JWT as an
# alternative to a workspace X-API-Key (see _resolve_remediation_actor in
# main.py) - same as every other admin page, this one goes through the
# shared Api helper and needs no separate connection step. An admin JWT
# isn't scoped to one workspace, so configs/logs are loaded across every
# workspace that has at least one deployment (via GET /admin/deployment-
# registry), not just one the admin manually picked.
#
# "Webhooks" and "Retraining" aren't separate resources - they're just
# action_type values on the same RemediationConfig - so there's one page
# here, not three; the sidebar was consolidated to match.
#
# There is no delete/deactivate/edit endpoint for a config - only create,
# list and test - so no delete/edit action is invented on this page.
# "Test" isn't a dry run (see services/remediation.py's fire_*
# functions): it really opens a GitHub issue / POSTs the webhook /
# dispatches the retrain workflow with test data, so it gets a Cancel/
# Confirm modal that says so plainly - nothing in Vela's own data is at
# risk (same reversible bucket as Teams' remove-member/revoke-access),
# but the real external side effect deserves a deliberate click.
#
# Color budget: the Configured rules table is configuration (calm,
# neutral, matches every other admin table); the Remediation logs table
# is the actual drift/trigger EVENT history, so that's where this screen
# spends color - drift score gets the same purple drift token Monitoring
# uses, and a log's status gets it too: "error" is a real problem so it's
# the real error/red status-dot, "success" stays uncolored (same house
# rule as everywhere else - a normal/working outcome is never colored,
# only the exception is). Both statuses are handled directly rather than
# through UI.statusBadge()'s STATUS_VARIANT map, which doesn't have
# "success" or "error" as keys (only "failed" maps to the error variant)
# - going through it as-is would silently render a real error as a
# neutral gray dot, burying exactly the signal this page exists to show.
# =========================================================================

@router.get("/admin/automation")
def admin_automation_redirect():
    return RedirectResponse(url="/admin/remediation", status_code=302)


@router.get("/admin/remediation", response_class=HTMLResponse)
def admin_remediation_page():
    ds_assets = (
        '<link rel="stylesheet" href="/static/css/ds/tokens.css?v=ds5">\n'
        '<link rel="stylesheet" href="/static/css/ds/base.css?v=ds5">\n'
        '<link rel="stylesheet" href="/static/css/ds/primitives.css?v=ds5">\n'
        '<link rel="stylesheet" href="/static/css/ds/shell.css?v=ds7">'
    )

    body = """
<div id="page-content" hidden>
  <div class="page-max">
    <div class="page-header">
      <div>
        <h1 class="page-title">Remediation</h1>
        <div class="page-description">Configure automatic actions when model drift exceeds a threshold. When triggered, Vela can open a GitHub issue, call a webhook, or start a retraining workflow.</div>
      </div>
      <div class="page-actions">
        <button class="btn btn-secondary btn-sm" id="refresh-btn" type="button">Refresh</button>
        <button class="btn btn-primary btn-sm" id="new-config-btn" type="button">New config</button>
      </div>
    </div>

    <div class="toolbar">
      <span class="input-group" style="flex:1 1 220px">
        <svg class="input-icon" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5"><circle cx="7" cy="7" r="4.5"/><path d="m11 11 3 3"/></svg>
        <input class="input" id="configs-filter" type="text" placeholder="Filter by deployment, action or target" autocomplete="off" style="flex:1;min-width:0">
      </span>
      <span class="toolbar-spacer"></span>
      <span class="text-muted" id="configs-count" style="font-size:var(--text-xs);flex-shrink:0"></span>
    </div>
    <div class="table-wrap" style="margin-bottom:var(--space-5)">
      <table class="table" style="min-width:720px">
        <thead><tr><th>Deployment</th><th>Threshold</th><th>Action</th><th>Target</th><th>Status</th><th>Last triggered</th><th class="num">Actions</th></tr></thead>
        <tbody id="configs-body"></tbody>
      </table>
    </div>

    <div class="section-label">Remediation logs</div>
    <div class="table-wrap">
      <table class="table" style="min-width:560px">
        <thead><tr><th>Deployment</th><th>Drift score</th><th>Action</th><th>Status</th><th>Triggered</th></tr></thead>
        <tbody id="logs-body"></tbody>
      </table>
    </div>
  </div>

  <div class="slideover-overlay" id="new-config-panel" hidden>
  <div class="slideover" role="dialog" aria-modal="true" aria-labelledby="new-config-panel-title">
    <div class="slideover-header">
      <div class="slideover-title" id="new-config-panel-title">New config</div>
      <button class="btn btn-ghost btn-sm btn-icon" id="close-new-config-panel" type="button" aria-label="Close">&#10005;</button>
    </div>
    <div class="slideover-body">
      <form class="form" id="new-config-form" novalidate>
        <div class="field">
          <label class="field-label" for="nc-dep">Deployment</label>
          <select class="select" id="nc-dep" required></select>
        </div>
        <div class="field"><label class="field-label" for="nc-threshold">Drift threshold</label><input class="input" type="number" id="nc-threshold" step="0.01" min="0" max="1" value="0.5"></div>
        <div class="field">
          <label class="field-label" for="nc-action">Action</label>
          <select class="select" id="nc-action">
            <option value="github_issue">GitHub issue</option>
            <option value="webhook">Webhook</option>
            <option value="retrain">Retrain</option>
          </select>
        </div>
        <div class="field">
          <label class="field-label" for="nc-target">Target</label>
          <input class="input" id="nc-target" placeholder="">
          <div class="field-hint" id="nc-target-hint"></div>
        </div>
        <div class="field-error" id="nc-error" role="alert"></div>
        <button class="btn btn-primary btn-block" type="submit" id="nc-submit">Create config</button>
      </form>
    </div>
  </div>
  </div>
</div>
<div id="loading-root" style="min-height:100vh;display:flex;align-items:center;justify-content:center;color:var(--text-muted);font-size:var(--text-sm)">Loading&hellip;</div>
"""

    script = """
<script>
  // Registry rows this admin has already loaded - used to resolve a
  // config/log's deployment_id to a real name instead of just "#N", and
  // to populate the New config panel's deployment picker. Also, since an
  // admin JWT isn't scoped to one workspace the way an API key is, this
  // is what determines *which* workspaces to ask /api/v1/remediations/
  // {workspace_id} and /api/v1/remediation-logs/{workspace_id} about -
  // every workspace with at least one deployment, unioned together.
  let registryDeployments = [];
  let cachedConfigs = [];

  function deploymentLabel(id) {
    const d = registryDeployments.find(r => r.id === id);
    return d ? d.name : ('Deployment #' + id);
  }

  function initRemediation() {
    const refreshBtn = document.getElementById('refresh-btn');
    if (refreshBtn) refreshBtn.addEventListener('click', () => loadAll());
    const filterInput = document.getElementById('configs-filter');
    if (filterInput) filterInput.addEventListener('input', renderConfigsTable);
    wireNewConfigPanel();
    loadAll();
  }

  async function loadAll() {
    const configsBody = document.getElementById('configs-body');
    const logsBody = document.getElementById('logs-body');
    configsBody.innerHTML = UI.skeletonRows(7, 3);
    logsBody.innerHTML = UI.skeletonRows(5, 3);
    try {
      registryDeployments = await Api.get('/admin/deployment-registry');
      const workspaceIds = Array.from(new Set(registryDeployments.map(d => d.workspace_id).filter(id => id != null)));

      const [configResults, logResults] = await Promise.all([
        Promise.allSettled(workspaceIds.map(ws => Api.get('/api/v1/remediations/' + ws))),
        Promise.allSettled(workspaceIds.map(ws => Api.get('/api/v1/remediation-logs/' + ws))),
      ]);
      cachedConfigs = configResults.filter(r => r.status === 'fulfilled').flatMap(r => r.value);
      const logs = logResults.filter(r => r.status === 'fulfilled').flatMap(r => r.value);

      renderConfigsTable();
      renderLogs(logs);
    } catch (e) {
      // Both tables share this one load - a failure here means neither
      // has real data, so both need to leave their skeleton state,
      // not just the one whose <tbody> happens to be listed first.
      cachedConfigs = [];
      configsBody.innerHTML = '<tr><td colspan="7">' + UI.errorState(e.message, loadAll) + '</td></tr>';
      logsBody.innerHTML = '<tr><td colspan="5">' + UI.errorState(e.message, loadAll) + '</td></tr>';
      const countEl = document.getElementById('configs-count');
      if (countEl) countEl.textContent = '';
    }
  }

  // Client-side only: filters the already-loaded cachedConfigs, same
  // pattern as the other migrated tables' filters.
  function renderConfigsTable() {
    const body = document.getElementById('configs-body');
    const countEl = document.getElementById('configs-count');
    const q = (document.getElementById('configs-filter').value || '').trim().toLowerCase();

    if (!cachedConfigs.length) {
      body.innerHTML = '<tr><td colspan="7">' + UI.emptyState('No remediation configs yet', 'Create one to automatically react when drift crosses a threshold.') + '</td></tr>';
      if (countEl) countEl.textContent = '';
      return;
    }

    const rows = cachedConfigs.filter(c => {
      if (!q) return true;
      return deploymentLabel(c.deployment_id).toLowerCase().includes(q)
        || (c.action_type || '').toLowerCase().includes(q)
        || (c.target || '').toLowerCase().includes(q);
    });

    if (countEl) {
      countEl.textContent = q
        ? rows.length + ' of ' + cachedConfigs.length
        : cachedConfigs.length + (cachedConfigs.length === 1 ? ' config' : ' configs');
    }

    if (!rows.length) {
      body.innerHTML = '<tr><td colspan="7">' + UI.emptyState('No matches', 'No config matches that filter.') + '</td></tr>';
      return;
    }

    body.innerHTML = rows.map(renderConfigRow).join('');
    body.querySelectorAll('[data-test]').forEach(btn => {
      btn.addEventListener('click', () => confirmTestConfig(btn.dataset.test, btn.dataset.name));
    });
  }

  // Plain configuration, not a live event - neutral throughout (Status
  // and Last triggered are facts about a rule, not the drift/trigger
  // events themselves; those get this screen's color budget, below).
  function renderConfigRow(c) {
    const label = deploymentLabel(c.deployment_id);
    return '<tr>' +
      '<td class="mono">' + UI.escapeHtml(label) + '</td>' +
      '<td>' + c.drift_threshold + '</td>' +
      '<td><span class="chip-mono">' + UI.escapeHtml(c.action_type) + '</span></td>' +
      '<td class="text-secondary" style="max-width:220px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">' + UI.escapeHtml(c.target || '—') + '</td>' +
      '<td>' + UI.statusBadge(c.is_active ? 'active' : 'inactive') + '</td>' +
      '<td class="text-secondary">' + (c.last_triggered_at ? UI.timeAgo(c.last_triggered_at) : 'Never') + '</td>' +
      '<td class="num"><button class="link-action" data-test="' + c.id + '" data-name="' + UI.escapeHtml(c.action_type) + ' for ' + UI.escapeHtml(label) + '" type="button">Test</button></td>' +
      '</tr>';
  }

  // The real drift/trigger event history - this table gets this screen's
  // color budget (see the route comment above): drift score always
  // reads as the drift-purple status-dot (every logged score crossed
  // its config's threshold, so it's always drift-relevant), and a
  // log's status is mapped directly rather than through
  // UI.statusBadge() - "error" is the real error/red variant, "success"
  // stays plain/uncolored, matching the rest of this system's rule that
  // only the exception ever takes color.
  function renderLogs(logs) {
    const body = document.getElementById('logs-body');
    if (!logs.length) {
      body.innerHTML = '<tr><td colspan="5">' + UI.emptyState('No remediation runs yet', 'Triggered actions will be logged here.') + '</td></tr>';
      return;
    }
    body.innerHTML = logs.map(l => {
      const isError = String(l.status).toLowerCase() === 'error';
      return '<tr>' +
        '<td class="mono">' + UI.escapeHtml(deploymentLabel(l.deployment_id)) + '</td>' +
        '<td>' + UI.statusDot(Number(l.drift_score).toFixed(3), 'drift') + '</td>' +
        '<td><span class="chip-mono">' + UI.escapeHtml(l.action_type) + '</span></td>' +
        '<td>' + UI.statusDot(isError ? 'Error' : 'Success', isError ? 'error' : 'neutral') + '</td>' +
        '<td class="text-secondary">' + UI.timeAgo(l.triggered_at) + '</td>' +
        '</tr>';
    }).join('');
  }

  // Not a dry run (see the route comment above) - this really fires the
  // configured action with test data, so it gets a plain Cancel/Confirm
  // before the same POST .../test call the legacy page made
  // unconditionally on click.
  function confirmTestConfig(id, name) {
    const overlay = UI.openModal({
      title: 'Test ' + name,
      bodyHtml: `
        <div class="alert alert-warning">
          <div><div class="alert-title">This is not a dry run</div>This will really fire this config's action right now &mdash; e.g. open a real GitHub issue or POST to the real webhook &mdash; using test data (a fake deployment, drift score 0.99).</div></div>
        </div>
      `,
      footerHtml: `<button class="btn btn-ghost" id="test-cancel" type="button">Cancel</button>
                   <button class="btn btn-primary" id="test-confirm" type="button">Fire test</button>`,
    });
    overlay.querySelector('#test-cancel').addEventListener('click', UI.closeModal);
    const confirmBtn = overlay.querySelector('#test-confirm');
    confirmBtn.addEventListener('click', async () => {
      confirmBtn.disabled = true;
      confirmBtn.textContent = 'Firing…';
      try {
        const result = await Api.post('/api/v1/remediations/' + id + '/test', {});
        const ok = result.status === 'success';
        UI.closeModal();
        UI.toast('Test ' + (ok ? 'succeeded' : 'failed') + ': ' + (result.response || result.status), ok ? 'success' : 'danger', 6000);
        loadAll();
      } catch (e) {
        UI.toast('Test failed: ' + (e.message || 'unknown error'), 'danger');
        confirmBtn.disabled = false;
        confirmBtn.textContent = 'Fire test';
      }
    });
  }

  function targetHintFor(actionType) {
    if (actionType === 'github_issue') return 'GitHub repo as "owner/repo" - optional, falls back to the server-configured repo if left blank.';
    if (actionType === 'webhook') return 'Webhook URL to POST a JSON payload to - required.';
    if (actionType === 'retrain') return 'GitHub Actions workflow filename to dispatch - optional, defaults to retrain.yml.';
    return '';
  }

  // ================================================================
  // New config slide-over - same 4 fields, same validation, same POST
  // as before; only the surface it lives in changed (this used to be an
  // always-visible form next to the tables).
  // ================================================================

  function renderDeploymentPicker() {
    const sel = document.getElementById('nc-dep');
    if (!registryDeployments.length) {
      sel.innerHTML = '<option value="">No deployments found</option>';
      sel.disabled = true;
      return;
    }
    sel.disabled = false;
    sel.innerHTML = registryDeployments.map(d => '<option value="' + d.id + '">' + UI.escapeHtml(d.name) + ' (ID ' + d.id + ')</option>').join('');
  }

  function wireNewConfigPanel() {
    const panel = document.getElementById('new-config-panel');
    const openBtn = document.getElementById('new-config-btn');
    const closeBtn = document.getElementById('close-new-config-panel');
    if (!panel || !openBtn) return;

    openBtn.addEventListener('click', () => {
      // Always populated right before showing, so it reflects whatever
      // loadAll() most recently fetched even if that changed since the
      // panel was last opened.
      renderDeploymentPicker();
      openSlideover('new-config-panel', '#nc-dep', closeNewConfigPanel);
    });
    closeBtn.addEventListener('click', closeNewConfigPanel);
    panel.addEventListener('click', (e) => { if (e.target === panel) closeNewConfigPanel(); });

    document.getElementById('nc-action').addEventListener('change', (e) => {
      document.getElementById('nc-target-hint').textContent = targetHintFor(e.target.value);
    });
    document.getElementById('nc-target-hint').textContent = targetHintFor('github_issue');

    document.getElementById('new-config-form').addEventListener('submit', async (e) => {
      e.preventDefault();
      const errorEl = document.getElementById('nc-error');
      const submitBtn = document.getElementById('nc-submit');
      const deployment_id = parseInt(document.getElementById('nc-dep').value, 10);
      const drift_threshold = parseFloat(document.getElementById('nc-threshold').value);
      const action_type = document.getElementById('nc-action').value;
      const target = document.getElementById('nc-target').value.trim();
      errorEl.textContent = '';
      if (!deployment_id) { errorEl.textContent = 'Deployment is required.'; return; }
      if (action_type === 'webhook' && !target) { errorEl.textContent = 'Webhook actions require a target URL.'; return; }
      submitBtn.disabled = true;
      submitBtn.textContent = 'Creating…';
      try {
        await Api.post('/api/v1/remediations', { deployment_id, drift_threshold, action_type, target });
        UI.toast('Remediation config created', 'success');
        closeNewConfigPanel();
        loadAll();
      } catch (err) {
        errorEl.textContent = err.message || 'Could not create config.';
      } finally {
        submitBtn.disabled = false;
        submitBtn.textContent = 'Create config';
      }
    });
  }

  function closeNewConfigPanel() {
    closeSlideoverChrome('new-config-panel');
    document.getElementById('new-config-form').reset();
    document.getElementById('nc-error').textContent = '';
    document.getElementById('nc-target-hint').textContent = targetHintFor('github_issue');
  }

  // ================================================================
  // Shared slide-over chrome (open/close/focus-trap) - same helper as
  // admin_teams_page/admin_api_keys_page, duplicated here since each
  // route's <script> is self-contained (no shared ds.js module yet).
  // ================================================================

  const slideoverState = {};

  function openSlideover(id, focusSelector, onClose) {
    const panel = document.getElementById(id);
    if (!panel) return;
    const state = { returnFocus: document.activeElement };
    state.keydownHandler = (e) => {
      if (e.key === 'Escape') { onClose(); return; }
      if (e.key !== 'Tab') return;
      const focusables = Array.from(panel.querySelectorAll(
        'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled])'
      )).filter(el => el.offsetParent !== null);
      if (!focusables.length) return;
      const first = focusables[0], last = focusables[focusables.length - 1];
      if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
      else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
    };
    slideoverState[id] = state;
    panel.hidden = false;
    document.addEventListener('keydown', state.keydownHandler);
    const first = focusSelector ? panel.querySelector(focusSelector) : null;
    if (first) first.focus();
  }

  function closeSlideoverChrome(id) {
    const panel = document.getElementById(id);
    const state = slideoverState[id];
    if (!panel || panel.hidden) return;
    panel.hidden = true;
    if (state && state.keydownHandler) document.removeEventListener('keydown', state.keydownHandler);
    if (state && state.returnFocus && document.contains(state.returnFocus)) state.returnFocus.focus();
    delete slideoverState[id];
  }
</script>"""

    ready = "initRemediation();"

    html = (
        "<!DOCTYPE html>\n<html lang=\"en\">\n<head>\n<meta charset=\"UTF-8\">\n"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">\n"
        "<title>Remediation - Vela Admin</title>\n" + ds_assets + "\n</head>\n<body>\n"
        + body
        + "\n" + _SCRIPTS + "\n" + script
        + _boot_script("/admin/remediation", "Remediation", ready)
        + "\n</body>\n</html>"
    )
    return html


# =========================================================================
# Documentation - /admin/docs
# =========================================================================

@router.get("/admin/docs", response_class=HTMLResponse)
def admin_docs_page():
    # Admin-only body: DOCS_BODY in _page_fragments.py is shared with
    # /app/docs (member_pages.py), so it isn't touched here - this is a
    # local DS rebuild with the same docs.js element IDs (docs-subtitle,
    # docs-model-select, card-result) so Docs.start({role:'admin'}) keeps
    # working unmodified. docs.js itself renders the picker's model
    # options plus every section/card/form below card-result using the
    # same shared class vocabulary (.card, .section-label, .field, .btn,
    # .badge) that ds/primitives.css also defines, so that generated
    # markup reskins for free once the bundle below switches - no JS
    # changes needed. /app/docs is unaffected by this migration.
    ds_assets = (
        '<link rel="stylesheet" href="/static/css/ds/tokens.css?v=ds5">\n'
        '<link rel="stylesheet" href="/static/css/ds/base.css?v=ds5">\n'
        '<link rel="stylesheet" href="/static/css/ds/primitives.css?v=ds5">\n'
        '<link rel="stylesheet" href="/static/css/ds/shell.css?v=ds7">'
    )

    body = """
<div id="page-content" hidden>
  <div class="page-narrow">
    <div class="page-header">
      <div>
        <h1 class="page-title">Documentation</h1>
        <div class="page-description" id="docs-subtitle">Select a model to view or document it.</div>
      </div>
    </div>

    <div class="card" style="margin-bottom:var(--space-5)">
      <div class="field" style="margin-bottom:0">
        <label class="field-label" for="docs-model-select">Model</label>
        <select class="select" id="docs-model-select" style="min-width:280px"></select>
      </div>
    </div>

    <div id="card-result"></div>
  </div>
</div>
<div id="loading-root" style="min-height:100vh;display:flex;align-items:center;justify-content:center;color:var(--text-muted);font-size:var(--text-sm)">Loading&hellip;</div>
"""

    ready = "Docs.start({role: 'admin'});"

    html = (
        "<!DOCTYPE html>\n<html lang=\"en\">\n<head>\n<meta charset=\"UTF-8\">\n"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">\n"
        "<title>Documentation - Vela Admin</title>\n" + ds_assets + "\n</head>\n<body>\n"
        + body
        + "\n" + _SCRIPTS + "\n" + DOCS_SCRIPTS_EXTRA
        + _boot_script("/admin/docs", "Documentation", ready)
        + "\n</body>\n</html>"
    )
    return html


# =========================================================================
# Settings - /admin/settings
# =========================================================================

@router.get("/admin/settings", response_class=HTMLResponse)
def admin_settings_page():
    # Admin-only body: SETTINGS_BODY in _page_fragments.py is shared with
    # /app/settings (member_pages.py), so it isn't touched here - this is
    # a local DS rebuild with the same settings.js element IDs
    # (acc-username/acc-name/acc-role, pw-form + its fields/error/submit)
    # so Settings.start(user) keeps working unmodified. /app/settings is
    # unaffected by this migration.
    ds_assets = (
        '<link rel="stylesheet" href="/static/css/ds/tokens.css?v=ds5">\n'
        '<link rel="stylesheet" href="/static/css/ds/base.css?v=ds5">\n'
        '<link rel="stylesheet" href="/static/css/ds/primitives.css?v=ds5">\n'
        '<link rel="stylesheet" href="/static/css/ds/shell.css?v=ds7">'
    )

    body = """
<div id="page-content" hidden>
  <div class="page-narrow">
    <div class="page-header">
      <div>
        <h1 class="page-title">Settings</h1>
        <div class="page-description">Your account and password.</div>
      </div>
    </div>

    <div class="section-label" style="margin-top:0">Account</div>
    <div class="card" style="margin-bottom:var(--space-6)">
      <div style="display:flex;justify-content:space-between;align-items:center;padding:.45rem 0;border-bottom:var(--border-width) solid var(--border-subtle)">
        <span class="text-secondary" style="font-size:var(--text-sm)">Username</span>
        <span id="acc-username" style="font-size:var(--text-sm)">&mdash;</span>
      </div>
      <div style="display:flex;justify-content:space-between;align-items:center;padding:.45rem 0;border-bottom:var(--border-width) solid var(--border-subtle)">
        <span class="text-secondary" style="font-size:var(--text-sm)">Name</span>
        <span id="acc-name" style="font-size:var(--text-sm)">&mdash;</span>
      </div>
      <div style="display:flex;justify-content:space-between;align-items:center;padding:.45rem 0">
        <span class="text-secondary" style="font-size:var(--text-sm)">Role</span>
        <span id="acc-role"></span>
      </div>
    </div>

    <div class="section-label">Change password</div>
    <div class="card">
      <form class="form" id="pw-form" novalidate>
        <div class="field">
          <label class="field-label" for="s-new-password">New password</label>
          <input class="input" type="password" id="s-new-password" autocomplete="new-password" required minlength="8">
        </div>
        <div class="field">
          <label class="field-label" for="s-confirm-password">Confirm new password</label>
          <input class="input" type="password" id="s-confirm-password" autocomplete="new-password" required minlength="8">
        </div>
        <div class="field-error" id="s-error" role="alert"></div>
        <button class="btn btn-primary" type="submit" id="s-submit">Update password</button>
      </form>
    </div>
  </div>
</div>
<div id="loading-root" style="min-height:100vh;display:flex;align-items:center;justify-content:center;color:var(--text-muted);font-size:var(--text-sm)">Loading&hellip;</div>
"""

    ready = "Settings.start(user);"

    html = (
        "<!DOCTYPE html>\n<html lang=\"en\">\n<head>\n<meta charset=\"UTF-8\">\n"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">\n"
        "<title>Settings - Vela Admin</title>\n" + ds_assets + "\n</head>\n<body>\n"
        + body
        + "\n" + _SCRIPTS + "\n" + SETTINGS_SCRIPTS_EXTRA
        + _boot_script("/admin/settings", "Settings", ready)
        + "\n</body>\n</html>"
    )
    return html


# =========================================================================
# Model Registry - /admin/models
#
# GET /admin/deployment-registry (every Deployment row) decides which
# rows exist; GET /models/status is merged in by id to attach each row's
# live health-check status, since the registry's own Deployment.status
# is only set once at deploy/upload time and doesn't track a running
# pod's actual reachability. No other source feeds this page - the two
# hardcoded core services (DistilBERT Sentiment / distilbart-mnli
# Zero-Shot) this used to also show, from before either was a real
# Deployment row, are gone.
# =========================================================================

@router.get("/admin/models", response_class=HTMLResponse)
def admin_models_page():
    # Phase 2: migrated to the ds/* design system (see admin_overview_page /
    # admin_deployments_page for the reference pattern). ds/* bundle for
    # this route only; every other admin page still uses _ASSETS. Shared JS
    # (_SCRIPTS) is theme-agnostic and unchanged.
    ds_assets = (
        '<link rel="stylesheet" href="/static/css/ds/tokens.css?v=ds5">\n'
        '<link rel="stylesheet" href="/static/css/ds/base.css?v=ds5">\n'
        '<link rel="stylesheet" href="/static/css/ds/primitives.css?v=ds5">\n'
        '<link rel="stylesheet" href="/static/css/ds/shell.css?v=ds7">'
    )

    body = """
<div id="page-content" hidden>
  <div class="page-max">
    <div class="page-header">
      <div>
        <h1 class="page-title">Model Registry</h1>
        <div class="page-description">Every model deployed on the platform.</div>
      </div>
      <div class="page-actions">
        <button class="btn btn-secondary btn-sm" id="refresh-btn" type="button">Refresh</button>
        <a class="btn btn-secondary btn-sm" href="/admin/deployments">Deploy model &rarr;</a>
      </div>
    </div>

    <div class="toolbar">
      <span class="input-group" style="flex:1 1 220px">
        <svg class="input-icon" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5"><circle cx="7" cy="7" r="4.5"/><path d="m11 11 3 3"/></svg>
        <input class="input" id="reg-filter" type="text" placeholder="Filter by name, task, source or status" autocomplete="off" style="flex:1;min-width:0">
      </span>
      <span class="toolbar-spacer"></span>
      <span class="text-muted" id="reg-count" style="font-size:var(--text-xs);flex-shrink:0"></span>
    </div>
    <div class="table-wrap">
      <table class="table" style="min-width:720px">
        <thead><tr><th>Model</th><th>Task</th><th>Source</th><th>Status</th><th class="num">Actions</th></tr></thead>
        <tbody id="registry-body"></tbody>
      </table>
    </div>
  </div>
</div>
<div id="loading-root" style="min-height:100vh;display:flex;align-items:center;justify-content:center;color:var(--text-muted);font-size:var(--text-sm)">Loading&hellip;</div>
"""

    script = """
<script>
  // Every row comes from the registry (the real DB Deployment, and the
  // source of truth for id/model_type/is_active - what management
  // actions below need); /models/status is merged in by id purely for
  // live health-check status, since Deployment.status is only ever set
  // once at deploy/upload time.
  let registryRows = [];
  let managementApiKey = '';

  function initModels() {
    const refreshBtn = document.getElementById('refresh-btn');
    if (refreshBtn) refreshBtn.addEventListener('click', () => loadRegistry());
    const filterInput = document.getElementById('reg-filter');
    if (filterInput) filterInput.addEventListener('input', renderRegistryTable);
    loadRegistry();
  }

  async function loadRegistry() {
    const body = document.getElementById('registry-body');
    body.innerHTML = UI.skeletonRows(5, 5);
    try {
      const [registry, live] = await Promise.all([
        Api.get('/admin/deployment-registry'), Api.get('/models/status')
      ]);
      const liveById = new Map(live.map(m => [m.id, m]));

      registryRows = registry.map(reg => {
        const l = liveById.get(reg.id);
        return { name: reg.name, task: reg.task_type, status: l ? l.status : reg.status, reg };
      });
      renderRegistryTable();
    } catch (e) {
      registryRows = [];
      body.innerHTML = '<tr><td colspan="5">' + UI.errorState(e.message, loadRegistry) + '</td></tr>';
      const countEl = document.getElementById('reg-count');
      if (countEl) countEl.textContent = '';
    }
  }

  // Client-side only: narrows the already-loaded rows by name / task /
  // source / status. CRITICAL: each visible row is rendered with its
  // ORIGINAL index into registryRows (registryRows itself is never
  // filtered), so the data-toggle-active / data-delete-model /
  // data-edit-task attributes and the registryRows[idx] lookups in
  // wireRegistryRows() always resolve to the right model regardless of
  // what the filter is showing.
  function renderRegistryTable() {
    const body = document.getElementById('registry-body');
    const countEl = document.getElementById('reg-count');
    const q = (document.getElementById('reg-filter').value || '').trim().toLowerCase();

    if (!registryRows.length) {
      body.innerHTML = '<tr><td colspan="5">' + UI.emptyState('No models registered yet', 'Deploy a model from the Deployments page to see it here.') + '</td></tr>';
      if (countEl) countEl.textContent = '';
      return;
    }

    const matches = registryRows
      .map((r, idx) => ({ r, idx }))
      .filter(({ r }) => {
        if (!q) return true;
        const source = r.reg ? r.reg.model_type : 'huggingface';
        return (r.name || '').toLowerCase().includes(q)
          || (r.task || '').toLowerCase().includes(q)
          || (source || '').toLowerCase().includes(q)
          || (r.status || '').toLowerCase().includes(q);
      });

    if (countEl) {
      countEl.textContent = q
        ? matches.length + ' of ' + registryRows.length
        : registryRows.length + (registryRows.length === 1 ? ' model' : ' models');
    }

    if (!matches.length) {
      body.innerHTML = '<tr><td colspan="5">' + UI.emptyState('No matches', 'No model matches that filter.') + '</td></tr>';
      return;
    }

    body.innerHTML = matches.map(({ r, idx }) => renderRegistryRow(r, idx)).join('');
    wireRegistryRows();
  }

  function renderRegistryRow(r, idx) {
    const modelType = r.reg ? r.reg.model_type : 'huggingface';
    const isActive = r.reg ? r.reg.is_active !== false : true;

    const docsHref = '/admin/docs' + (r.reg ? '?deployment_id=' + r.reg.id : '');
    const actions = ['<a class="link-action" href="' + docsHref + '">Docs &rarr;</a>'];
    if (r.reg) {
      actions.push('<button class="link-action" data-toggle-active="' + idx + '" type="button">' + (isActive ? 'Disable' : 'Enable') + '</button>');
      actions.push('<button class="link-action link-danger" data-delete-model="' + idx + '" type="button">Delete</button>');
    }

    return '<tr>' +
      '<td class="mono">' + UI.escapeHtml(r.name) + '</td>' +
      '<td id="task-cell-' + idx + '">' + taskCellHtml(r, idx) + '</td>' +
      '<td class="text-secondary">' + UI.escapeHtml(modelType) + '</td>' +
      '<td>' + UI.statusBadge(r.status) + (isActive ? '' : ' ' + UI.statusDot('Disabled', 'offline')) + '</td>' +
      '<td class="num"><span style="display:inline-flex;gap:var(--space-3);align-items:center;justify-content:flex-end;flex-wrap:wrap">' + actions.join('') + '</span></td>' +
      '</tr>';
  }

  // Only custom models get the inline pencil - task_type on a
  // HuggingFace deployment mirrors deploy-model.yml's own "task" input
  // and editing it here wouldn't change anything about the running
  // deployment, just make the label lie about what dispatched it.
  function taskCellHtml(row, idx) {
    const isCustom = (row.reg ? row.reg.model_type : 'huggingface') === 'custom';
    if (!isCustom) return '<span class="chip-mono">' + UI.escapeHtml(row.task) + '</span>';
    return '<span class="chip-mono">' + UI.escapeHtml(row.task) + '</span>' +
      '<button class="link-action" data-edit-task="' + idx + '" type="button" style="margin-left:var(--space-2)" title="Edit task type" aria-label="Edit task type">Edit</button>';
  }

  function renderTaskCell(row, idx) {
    const cell = document.getElementById('task-cell-' + idx);
    if (!cell) return;
    cell.innerHTML = taskCellHtml(row, idx);
    const btn = cell.querySelector('[data-edit-task]');
    if (btn) btn.addEventListener('click', () => startEditTask(row, idx));
  }

  function startEditTask(row, idx) {
    if (!row.reg) return;
    const cell = document.getElementById('task-cell-' + idx);
    if (!cell) return;
    cell.innerHTML =
      '<span style="display:inline-flex;gap:var(--space-2);align-items:center;flex-wrap:wrap">' +
      '<input class="input" id="task-edit-' + idx + '" style="height:26px;font-size:var(--text-sm);width:11rem" value="' + UI.escapeHtml(row.task) + '">' +
      '<button class="btn btn-primary btn-sm" id="task-save-' + idx + '" type="button">Save</button>' +
      '<button class="btn btn-ghost btn-sm" id="task-cancel-' + idx + '" type="button">Cancel</button>' +
      '</span>';

    const input = document.getElementById('task-edit-' + idx);
    const saveBtn = document.getElementById('task-save-' + idx);
    const cancelBtn = document.getElementById('task-cancel-' + idx);
    input.focus();
    input.select();

    const cancel = () => renderTaskCell(row, idx);
    const save = async () => {
      const newTask = input.value.trim();
      if (!newTask) { input.focus(); return; }
      saveBtn.disabled = true;
      saveBtn.textContent = 'Saving…';
      try {
        await Api.patch('/api/v1/deployment/' + row.reg.id + '/task-type', { task_type: newTask });
        row.task = newTask;
        row.reg.task_type = newTask;
        renderTaskCell(row, idx);
        UI.toast('Task type updated', 'success');
      } catch (e) {
        UI.toast(e.message || 'Could not update task type', 'danger');
        saveBtn.disabled = false;
        saveBtn.textContent = 'Save';
      }
    };

    cancelBtn.addEventListener('click', cancel);
    saveBtn.addEventListener('click', save);
    input.addEventListener('keydown', (e) => {
      if (e.key === 'Escape') cancel();
      if (e.key === 'Enter') save();
    });
  }

  function wireRegistryRows() {
    document.querySelectorAll('[data-toggle-active]').forEach(btn => {
      const idx = parseInt(btn.dataset.toggleActive, 10);
      btn.addEventListener('click', () => toggleActive(registryRows[idx], btn));
    });
    document.querySelectorAll('[data-delete-model]').forEach(btn => {
      const idx = parseInt(btn.dataset.deleteModel, 10);
      btn.addEventListener('click', () => confirmDeleteModel(registryRows[idx]));
    });
    document.querySelectorAll('[data-edit-task]').forEach(btn => {
      const idx = parseInt(btn.dataset.editTask, 10);
      btn.addEventListener('click', () => startEditTask(registryRows[idx], idx));
    });
  }

  // Disable/Enable and Delete all need an unscoped workspace API key
  // (same X-API-Key auth every /api/v1/* write endpoint in this app
  // uses) - prompted for once, lazily, and cached for the rest of the
  // page's lifetime rather than shown as a permanent field.
  function ensureApiKey() {
    if (managementApiKey) return Promise.resolve(managementApiKey);
    return new Promise((resolve) => {
      const overlay = UI.openModal({
        title: 'API key required',
        bodyHtml: `
          <p class="text-secondary" style="font-size:var(--text-sm);margin-bottom:var(--space-3)">An unscoped workspace API key is needed to manage models - see API Keys.</p>
          <div class="field"><label class="field-label" for="reg-api-key">API key</label><input class="input" type="password" id="reg-api-key" placeholder="aodp_your_admin_key"></div>
        `,
        footerHtml: `<button class="btn btn-ghost" id="reg-key-cancel" type="button">Cancel</button>
                     <button class="btn btn-primary" id="reg-key-save" type="button">Continue</button>`,
      });
      const finish = (value) => { UI.closeModal(); resolve(value); };
      overlay.querySelector('#reg-key-cancel').addEventListener('click', () => finish(null));
      const input = overlay.querySelector('#reg-api-key');
      const save = () => {
        const value = input.value.trim();
        if (!value) return;
        managementApiKey = value;
        finish(value);
      };
      overlay.querySelector('#reg-key-save').addEventListener('click', save);
      input.addEventListener('keydown', (e) => { if (e.key === 'Enter') save(); });
    });
  }

  async function toggleActive(row, btn) {
    if (!row.reg) return;
    const key = await ensureApiKey();
    if (!key) return;
    const newActive = !(row.reg.is_active !== false);
    btn.disabled = true;
    try {
      const res = await fetch('/api/v1/deployment/' + row.reg.id, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', 'X-API-Key': key },
        body: JSON.stringify({ is_active: newActive }),
      });
      const data = await res.json().catch(() => null);
      if (!res.ok) throw new Error((data && data.detail) || 'Could not update model');
      UI.toast(newActive ? 'Model enabled' : 'Model disabled', 'success');
      loadRegistry();
    } catch (e) {
      UI.toast(e.message || 'Could not update model', 'danger');
      btn.disabled = false;
    }
  }

  // Fetch the key BEFORE opening the type-to-confirm dialog, not from
  // inside its button handler - UI.openModal() closes whatever modal is
  // currently open before showing a new one, so nesting them here would
  // close the confirm dialog out from under itself.
  async function confirmDeleteModel(row) {
    if (!row.reg) return;
    const key = await ensureApiKey();
    if (!key) return;

    const overlay = UI.openModal({
      title: 'Delete ' + row.name,
      bodyHtml: `
        <div class="alert alert-danger" style="margin-bottom:var(--space-3)">
          <div><div class="alert-title">This cannot be undone</div><div>This will remove the model and revoke all team access. Type the model name to confirm.</div></div>
        </div>
        <div class="field">
          <label class="field-label" for="del-confirm-name">Model name</label>
          <input class="input" id="del-confirm-name" placeholder="${UI.escapeHtml(row.name)}">
        </div>
        <div class="field-error" id="del-confirm-error" role="alert"></div>
      `,
      footerHtml: `<button class="btn btn-ghost" id="del-cancel" type="button">Cancel</button>
                   <button class="btn btn-danger" id="del-confirm" type="button" disabled>Delete</button>`,
    });
    const input = overlay.querySelector('#del-confirm-name');
    const confirmBtn = overlay.querySelector('#del-confirm');
    const errorEl = overlay.querySelector('#del-confirm-error');

    input.addEventListener('input', () => {
      confirmBtn.disabled = input.value !== row.name;
    });
    overlay.querySelector('#del-cancel').addEventListener('click', UI.closeModal);

    confirmBtn.addEventListener('click', async () => {
      confirmBtn.disabled = true;
      confirmBtn.textContent = 'Deleting…';
      errorEl.textContent = '';
      try {
        const path = row.reg.model_type === 'custom'
          ? '/api/v1/custom-model/' + row.reg.id
          : '/api/v1/deployment/' + row.reg.id;
        const res = await fetch(path, { method: 'DELETE', headers: { 'X-API-Key': key } });
        const data = await res.json().catch(() => null);
        if (!res.ok) throw new Error((data && data.detail) || 'Could not delete model');
        UI.closeModal();
        UI.toast('Model deleted', 'success');
        loadRegistry();
      } catch (e) {
        errorEl.textContent = e.message || 'Could not delete model.';
        confirmBtn.disabled = false;
        confirmBtn.textContent = 'Delete';
      }
    });
  }
</script>"""

    ready = "initModels();"

    html = (
        "<!DOCTYPE html>\n<html lang=\"en\">\n<head>\n<meta charset=\"UTF-8\">\n"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">\n"
        "<title>Model Registry - Vela Admin</title>\n" + ds_assets + "\n</head>\n<body>\n"
        + body
        + "\n" + _SCRIPTS + "\n" + script
        + _boot_script("/admin/models", "Model Registry", ready)
        + "\n</body>\n</html>"
    )
    return html


# =========================================================================
# Deployment Manager - /admin/deployments
# =========================================================================

@router.get("/admin/deployments", response_class=HTMLResponse)
def admin_deployments_page():
    # Phase 2: migrated to the ds/* design system (see admin_overview_page
    # for the reference pattern). ds/* bundle for this route only; every
    # other admin page still uses _ASSETS. Shared JS (_SCRIPTS) unchanged.
    ds_assets = (
        '<link rel="stylesheet" href="/static/css/ds/tokens.css?v=ds5">\n'
        '<link rel="stylesheet" href="/static/css/ds/base.css?v=ds5">\n'
        '<link rel="stylesheet" href="/static/css/ds/primitives.css?v=ds5">\n'
        '<link rel="stylesheet" href="/static/css/ds/shell.css?v=ds7">'
    )

    body = """
<div id="page-content" hidden>
  <div class="page-max">
    <div class="page-header">
      <div>
        <h1 class="page-title">Deployments</h1>
        <div class="page-description">Operational status of every deployment.</div>
      </div>
      <div class="page-actions">
        <button class="btn btn-secondary btn-sm" id="refresh-btn" type="button">Refresh</button>
        <button class="btn btn-primary btn-sm" id="open-deploy-panel" type="button">Deploy model</button>
      </div>
    </div>

    <div class="toolbar">
      <span class="input-group" style="flex:1 1 220px">
        <svg class="input-icon" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5"><circle cx="7" cy="7" r="4.5"/><path d="m11 11 3 3"/></svg>
        <input class="input" id="dep-filter" type="text" placeholder="Filter by name, model or status" autocomplete="off" style="flex:1;min-width:0">
      </span>
      <span class="toolbar-spacer"></span>
      <span class="text-muted" id="dep-count" style="font-size:var(--text-xs);flex-shrink:0"></span>
    </div>
    <div class="table-wrap">
      <table class="table" style="min-width:680px">
        <thead><tr><th>Deployment</th><th>Model</th><th>Task</th><th>Status</th><th class="num">Replicas</th><th>Managed by</th></tr></thead>
        <tbody id="deployments-body"></tbody>
      </table>
    </div>
  </div>

  <div class="slideover-overlay" id="deploy-panel" hidden>
  <div class="slideover" role="dialog" aria-modal="true" aria-labelledby="deploy-panel-title">
    <div class="slideover-header">
      <div class="slideover-title" id="deploy-panel-title">Deploy a model</div>
      <button class="btn btn-ghost btn-sm btn-icon" id="close-deploy-panel" type="button" aria-label="Close">&#10005;</button>
    </div>
    <div class="slideover-body">
      <div class="segmented segmented-block" role="tablist" aria-label="Deployment type" style="margin-bottom:var(--space-5)">
        <button class="segmented-option is-active" id="seg-hf" type="button" role="tab" aria-selected="true" aria-controls="deploy-form">HuggingFace</button>
        <button class="segmented-option" id="seg-custom" type="button" role="tab" aria-selected="false" aria-controls="custom-deploy-form">Custom model</button>
      </div>

      <form class="form" id="deploy-form" novalidate>
        <div class="field">
          <label class="field-label" for="dp-model">HuggingFace model name</label>
          <input class="input" id="dp-model" placeholder="e.g. distilbert-base-uncased-finetuned-sst-2-english" required>
        </div>
        <div class="field">
          <label class="field-label" for="dp-task">Task</label>
          <select class="select" id="dp-task">
            <option value="sentiment-analysis">Sentiment Analysis</option>
            <option value="zero-shot-classification">Zero-Shot Classification</option>
            <option value="text-classification">Text Classification</option>
            <option value="token-classification">Named Entity Recognition / Token Classification</option>
            <option value="text-generation">Text Generation</option>
            <option value="summarization">Summarization</option>
            <option value="translation">Translation</option>
            <option value="question-answering">Question Answering</option>
            <option value="fill-mask">Fill Mask</option>
            <option value="image-classification">Image Classification</option>
          </select>
        </div>
        <div class="field">
          <label class="field-label" for="dp-name">Deployment name</label>
          <input class="input" id="dp-name" placeholder="lowercase-with-hyphens" required>
          <div class="field-hint">Lowercase letters, numbers, and hyphens only.</div>
        </div>
        <div class="field-error" id="dp-error" role="alert"></div>
        <div id="dp-success" hidden style="margin-bottom:var(--space-3)"></div>
        <button class="btn btn-primary btn-block" type="submit" id="dp-submit">Deploy via GitHub Actions</button>
      </form>

      <form class="form" id="custom-deploy-form" novalidate hidden>
        <a class="link-action" style="font-size:var(--text-xs);display:inline-block;margin-bottom:var(--space-3)" href="/api/v1/custom-model-template" download>Download predict.py template &rarr;</a>
        <div class="field">
          <label class="field-label" for="cm-name">Deployment name</label>
          <input class="input" id="cm-name" placeholder="lowercase-with-hyphens" required>
          <div class="field-hint">Lowercase letters, numbers, and hyphens only.</div>
        </div>
        <div class="field">
          <label class="field-label" for="cm-task-type">Task type <span class="field-optional">optional</span></label>
          <input class="input" id="cm-task-type" placeholder="e.g. fraud-detection, clinical-risk, tabular-classification">
          <div class="field-hint">Free-text label for what the model does &mdash; shown on the Model Registry.</div>
        </div>
        <div class="field">
          <label class="field-label" for="cm-input-type">Input type</label>
          <select class="select" id="cm-input-type">
            <option value="text">Text</option>
            <option value="json">JSON / Structured data</option>
            <option value="file">File / Image</option>
          </select>
        </div>
        <div class="field" id="cm-schema-field" hidden>
          <label class="field-label" for="cm-input-schema">Input schema</label>
          <textarea class="textarea" id="cm-input-schema" placeholder='{"age": "number", "income": "number", "risk_score": "number"}'></textarea>
          <div class="field-hint">Describes the JSON fields callers should send &mdash; shown to them, not enforced.</div>
        </div>
        <div class="field">
          <label class="field-label" for="cm-predict-file">predict.py</label>
          <label class="file-input">
            <input type="file" id="cm-predict-file" accept=".py" required>
            <span class="file-input-name is-empty" data-placeholder="No file selected">No file selected</span>
            <span class="file-input-btn">Choose file</span>
          </label>
        </div>
        <div class="field">
          <label class="field-label" for="cm-model-files">Model files</label>
          <label class="file-input">
            <input type="file" id="cm-model-files" accept=".pkl,.joblib,.pt,.bin,.onnx,.h5,.safetensors" multiple required>
            <span class="file-input-name is-empty" data-placeholder="No files selected">No files selected</span>
            <span class="file-input-btn">Choose files</span>
          </label>
        </div>
        <div class="field">
          <label class="field-label" for="cm-requirements-file">requirements.txt <span class="field-optional">optional</span></label>
          <label class="file-input">
            <input type="file" id="cm-requirements-file" accept=".txt">
            <span class="file-input-name is-empty" data-placeholder="No file selected">No file selected</span>
            <span class="file-input-btn">Choose file</span>
          </label>
          <div class="field-hint">List any Python packages your predict.py needs beyond scikit-learn, joblib, pandas, numpy.</div>
        </div>
        <div class="field-error" id="cm-error" role="alert"></div>
        <div id="cm-success" hidden style="margin-bottom:var(--space-3)"></div>
        <button class="btn btn-primary btn-block" type="submit" id="cm-submit">Upload and deploy</button>
      </form>
    </div>
  </div>
  </div>
</div>
<div id="loading-root" style="min-height:100vh;display:flex;align-items:center;justify-content:center;color:var(--text-muted);font-size:var(--text-sm)">Loading&hellip;</div>
"""

    script = """
<script>
  let deploymentRows = [];
  let deployPanelReturnFocus = null;

  function initDeployments() {
    const refreshBtn = document.getElementById('refresh-btn');
    if (refreshBtn) refreshBtn.addEventListener('click', () => loadDeployments());
    const filterInput = document.getElementById('dep-filter');
    if (filterInput) filterInput.addEventListener('input', renderDeploymentRows);

    wireDeployPanel();
    wireSegmentedControl();
    wireFileInputs(document);

    loadDeployments();
  }

  // ---- Deploy slide-over -------------------------------------------------
  function wireDeployPanel() {
    const panel = document.getElementById('deploy-panel');
    const openBtn = document.getElementById('open-deploy-panel');
    const closeBtn = document.getElementById('close-deploy-panel');
    if (!panel || !openBtn) return;

    openBtn.addEventListener('click', () => {
      deployPanelReturnFocus = document.activeElement;
      panel.hidden = false;
      document.addEventListener('keydown', deployPanelKeydown);
      const first = panel.querySelector('.form:not([hidden]) .input, .form:not([hidden]) .select');
      if (first) first.focus();
    });
    closeBtn.addEventListener('click', closeDeployPanel);
    panel.addEventListener('click', (e) => { if (e.target === panel) closeDeployPanel(); });
  }

  function closeDeployPanel() {
    const panel = document.getElementById('deploy-panel');
    if (!panel || panel.hidden) return;
    panel.hidden = true;
    document.removeEventListener('keydown', deployPanelKeydown);
    if (deployPanelReturnFocus && document.contains(deployPanelReturnFocus)) deployPanelReturnFocus.focus();
    deployPanelReturnFocus = null;
  }

  function deployPanelKeydown(e) {
    if (e.key === 'Escape') { closeDeployPanel(); return; }
    // Minimal focus containment: wrap Tab within the panel.
    if (e.key !== 'Tab') return;
    const panel = document.getElementById('deploy-panel');
    const focusables = Array.from(panel.querySelectorAll(
      'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled])'
    )).filter(el => el.offsetParent !== null);
    if (!focusables.length) return;
    const first = focusables[0], last = focusables[focusables.length - 1];
    if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
    else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
  }

  // ---- Segmented control (HuggingFace | Custom model) -------------------
  // Show/hide only - both forms stay in the DOM, every field id and the
  // submit handlers below are untouched.
  function wireSegmentedControl() {
    const segHf = document.getElementById('seg-hf');
    const segCustom = document.getElementById('seg-custom');
    if (!segHf || !segCustom) return;
    segHf.addEventListener('click', () => showSegment('hf'));
    segCustom.addEventListener('click', () => showSegment('custom'));
  }

  function showSegment(which) {
    const hf = which !== 'custom';
    document.getElementById('deploy-form').hidden = !hf;
    document.getElementById('custom-deploy-form').hidden = hf;
    for (const [id, on] of [['seg-hf', hf], ['seg-custom', !hf]]) {
      const el = document.getElementById(id);
      el.classList.toggle('is-active', on);
      el.setAttribute('aria-selected', String(on));
    }
    const active = document.querySelector('.slideover-body .form:not([hidden])');
    const firstField = active && active.querySelector('.input, .select');
    if (firstField) firstField.focus();
  }

  // ---- Styled file inputs ---------------------------------------------
  // Purely visual: the real <input type="file"> is untouched (id, name,
  // .files, accept, multiple, required all preserved) - this only mirrors
  // its selection into the .file-input-name span.
  function syncFileInput(input) {
    const wrap = input.closest('.file-input');
    if (!wrap) return;
    const nameEl = wrap.querySelector('.file-input-name');
    if (!nameEl) return;
    const placeholder = nameEl.dataset.placeholder || 'No file selected';
    const n = input.files ? input.files.length : 0;
    if (!n) { nameEl.textContent = placeholder; nameEl.classList.add('is-empty'); }
    else if (n === 1) { nameEl.textContent = input.files[0].name; nameEl.classList.remove('is-empty'); }
    else { nameEl.textContent = n + ' files selected'; nameEl.classList.remove('is-empty'); }
  }

  function wireFileInputs(root) {
    root.querySelectorAll('.file-input > input[type="file"]').forEach(input => {
      input.addEventListener('change', () => syncFileInput(input));
      syncFileInput(input);
    });
  }

  function resetFileInputs(formEl) {
    formEl.querySelectorAll('.file-input > input[type="file"]').forEach(syncFileInput);
  }

  async function loadDeployments() {
    const body = document.getElementById('deployments-body');
    body.innerHTML = UI.skeletonRows(6, 3);
    try {
      const [deployments, registry] = await Promise.all([
        Api.get('/deployments'), Api.get('/admin/deployment-registry')
      ]);
      const registryByName = new Map(registry.map(r => [r.name, r]));

      // GET /deployments reads model/task straight off the k8s Deployment
      // (MODEL_NAME/TASK_TYPE env vars) - custom-runner pods only ever set
      // INPUT_TYPE/INPUT_SCHEMA, so both come back "unknown" for every
      // custom model there. The registry (DB Deployment row) has the real
      // values, so it wins whenever a match exists - same fix as the
      // task_type column on /admin/models, for the same underlying reason.
      // It also carries model_type, which "Managed by" shows instead of
      // the old always-"platform"/hardcoded-"core service" label.
      deploymentRows = deployments.map(d => {
        const reg = registryByName.get(d.name) || null;
        return {
          name: d.name, model: (reg && reg.model_name) || d.model_name, task: (reg && reg.task_type) || d.task_type,
          status: d.status, replicas: d.ready + '/' + d.desired, model_type: reg ? reg.model_type : 'huggingface',
        };
      });
      renderDeploymentRows();
    } catch (e) {
      deploymentRows = [];
      body.innerHTML = '<tr><td colspan="6">' + UI.errorState(e.message, loadDeployments) + '</td></tr>';
      const countEl = document.getElementById('dep-count');
      if (countEl) countEl.textContent = '';
    }
  }

  // Client-side only: narrows the already-loaded rows by name / model /
  // task / status. The filter box never re-fetches - no backend call.
  function renderDeploymentRows() {
    const body = document.getElementById('deployments-body');
    const countEl = document.getElementById('dep-count');
    const q = (document.getElementById('dep-filter').value || '').trim().toLowerCase();

    if (!deploymentRows.length) {
      body.innerHTML = '<tr><td colspan="6">' + UI.emptyState('No deployments yet', 'Use the forms on the left to deploy your first model.') + '</td></tr>';
      if (countEl) countEl.textContent = '';
      return;
    }

    const rows = q
      ? deploymentRows.filter(r =>
          (r.name || '').toLowerCase().includes(q) ||
          (r.model || '').toLowerCase().includes(q) ||
          (r.task || '').toLowerCase().includes(q) ||
          (r.status || '').toLowerCase().includes(q))
      : deploymentRows;

    if (countEl) {
      countEl.textContent = q
        ? rows.length + ' of ' + deploymentRows.length
        : deploymentRows.length + (deploymentRows.length === 1 ? ' deployment' : ' deployments');
    }

    if (!rows.length) {
      body.innerHTML = '<tr><td colspan="6">' + UI.emptyState('No matches', 'No deployment matches that filter.') + '</td></tr>';
      return;
    }

    body.innerHTML = rows.map(r =>
      '<tr><td class="mono">' + UI.escapeHtml(r.name) + '</td><td class="text-secondary">' + UI.escapeHtml(r.model || '—') + '</td><td><span class="chip-mono">' + UI.escapeHtml(r.task) + '</span></td>' +
      '<td>' + UI.statusBadge(r.status) + '</td><td class="num text-secondary">' + r.replicas + '</td><td class="text-secondary">' + UI.escapeHtml(r.model_type) + '</td></tr>'
    ).join('');
  }

  document.getElementById('deploy-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    const errorEl = document.getElementById('dp-error');
    const successEl = document.getElementById('dp-success');
    const submitBtn = document.getElementById('dp-submit');
    errorEl.textContent = '';
    successEl.hidden = true;
    const model_name = document.getElementById('dp-model').value.trim();
    const task_type = document.getElementById('dp-task').value;
    const deployment_name = document.getElementById('dp-name').value.trim();
    if (!model_name || !deployment_name) { errorEl.textContent = 'Fill in all fields.'; return; }
    if (!/^[a-z0-9-]+$/.test(deployment_name)) { errorEl.textContent = 'Deployment name: lowercase letters, numbers, hyphens only.'; return; }
    submitBtn.disabled = true;
    submitBtn.textContent = 'Triggering…';
    try {
      const result = await Api.post('/deploy-model', { model_name, task_type, deployment_name });
      successEl.hidden = false;
      successEl.innerHTML =
        '<div class="alert alert-success"><div>' +
        '<div class="alert-title">Deployment triggered</div>' +
        '&ldquo;' + UI.escapeHtml(deployment_name) + '&rdquo; will appear in the table in ~5&ndash;10 min.' +
        (result.deployment_id ? ' <a class="link-action" href="/admin/docs?deployment_id=' + result.deployment_id + '">Document it now &rarr;</a>' : '') +
        '</div></div>';
      UI.toast('Deployment triggered', 'success');
      document.getElementById('deploy-form').reset();
    } catch (err) {
      errorEl.textContent = err.message || 'Could not trigger deployment.';
    } finally {
      submitBtn.disabled = false;
      submitBtn.textContent = 'Deploy via GitHub Actions';
    }
  });

  document.getElementById('cm-input-type').addEventListener('change', (e) => {
    document.getElementById('cm-schema-field').hidden = e.target.value !== 'json';
  });

  document.getElementById('custom-deploy-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    const errorEl = document.getElementById('cm-error');
    const successEl = document.getElementById('cm-success');
    const submitBtn = document.getElementById('cm-submit');
    errorEl.textContent = '';
    successEl.hidden = true;

    const deployment_name = document.getElementById('cm-name').value.trim();
    const task_type = document.getElementById('cm-task-type').value.trim();
    const input_type = document.getElementById('cm-input-type').value;
    const input_schema = document.getElementById('cm-input-schema').value.trim();
    const predictFile = document.getElementById('cm-predict-file').files[0];
    const modelFiles = document.getElementById('cm-model-files').files;
    const requirementsFile = document.getElementById('cm-requirements-file').files[0];

    if (!deployment_name || !predictFile || !modelFiles.length) {
      errorEl.textContent = 'Fill in all required fields.';
      return;
    }
    if (!/^[a-z0-9-]+$/.test(deployment_name)) {
      errorEl.textContent = 'Deployment name: lowercase letters, numbers, hyphens only.';
      return;
    }

    submitBtn.disabled = true;
    submitBtn.textContent = 'Uploading files…';
    // The upload + MinIO write + workflow dispatch all happen inside one
    // request/response - there's no real "upload finished, now
    // triggering" boundary to observe. This timer approximates it so the
    // button doesn't just sit on "Uploading files…" for however long the
    // whole thing takes.
    const stageTimer = setTimeout(() => { submitBtn.textContent = 'Triggering deployment…'; }, 1200);

    try {
      const workspaces = await Api.get('/workspaces');
      if (!workspaces.length) throw new Error('No workspace found - create a team first.');

      const form = new FormData();
      form.append('deployment_name', deployment_name);
      form.append('input_type', input_type);
      form.append('workspace_id', workspaces[0].id);
      if (task_type) form.append('task_type', task_type);
      if (input_type === 'json' && input_schema) form.append('input_schema', input_schema);
      form.append('predict_file', predictFile);
      Array.from(modelFiles).forEach(f => form.append('model_files', f));
      if (requirementsFile) form.append('requirements_file', requirementsFile);

      // Uses the logged-in admin's JWT session (Authorization: Bearer) -
      // the backend accepts that in place of a workspace X-API-Key for
      // admins, so this form no longer needs one of its own.
      const res = await fetch('/api/v1/upload-custom-model', {
        method: 'POST',
        headers: { 'Authorization': 'Bearer ' + Api.getToken() },
        body: form,
      });
      const text = await res.text();
      let data = null;
      if (text) { try { data = JSON.parse(text); } catch (parseErr) { data = null; } }
      if (!res.ok) throw new Error((data && data.detail) || res.statusText || 'Upload failed');

      clearTimeout(stageTimer);
      submitBtn.textContent = 'Deployment queued!';
      successEl.hidden = false;
      successEl.innerHTML =
        '<div class="alert alert-success"><div>' +
        '<div class="alert-title">Deployment queued</div>' +
        'Deployment #' + data.deployment_id + ' has been queued.' +
        '</div></div>';
      UI.toast('Custom model deployment triggered', 'success');
      document.getElementById('custom-deploy-form').reset();
      resetFileInputs(document.getElementById('custom-deploy-form'));
      document.getElementById('cm-schema-field').hidden = true;
      setTimeout(() => { submitBtn.textContent = 'Upload and deploy'; }, 2000);
      pollCustomModelStatus(data.deployment_id, successEl);
    } catch (err) {
      clearTimeout(stageTimer);
      submitBtn.textContent = 'Upload and deploy';
      errorEl.textContent = err.message || 'Could not upload and deploy.';
    } finally {
      submitBtn.disabled = false;
    }
  });

  // Real-time status after upload: GET /api/v1/custom-model-status/{id}
  // checks the Kubernetes download Job and Deployment directly (see
  // backend/app/services/k8s_custom.py get_status()) rather than
  // tracking anything server-side, so it's safe to just poll on a
  // timer - no session/queue state to lose on a page reload.
  function customStatusLabel(phase) {
    return {
      downloading: 'Downloading model files…',
      provisioning: 'Starting…',
      running: 'Running',
      failed: 'Failed',
      unknown: 'Unknown',
    }[phase] || phase;
  }

  // Maps a poll phase to a ds alert modifier: running -> success,
  // failed -> danger, anything still in progress -> warning.
  function customStatusVariant(phase) {
    if (phase === 'running') return 'success';
    if (phase === 'failed') return 'danger';
    return 'warning';
  }

  function pollCustomModelStatus(deploymentId, statusEl) {
    const maxAttempts = 60; // ~5 minutes at 5s intervals - then just stop; the table above still reflects whatever the last known status was.
    let attempts = 0;

    async function tick() {
      attempts += 1;
      try {
        const res = await fetch('/api/v1/custom-model-status/' + deploymentId, {
          headers: { 'Authorization': 'Bearer ' + Api.getToken() },
        });
        const data = await res.json().catch(() => null);
        const phase = (data && data.phase) || 'unknown';
        const detail = data && data.detail ? ' (' + UI.escapeHtml(data.detail) + ')' : '';
        statusEl.hidden = false;
        statusEl.innerHTML =
          '<div class="alert alert-' + customStatusVariant(phase) + '"><div>' +
          '<div class="alert-title">' + UI.escapeHtml(customStatusLabel(phase)) + '</div>' +
          'Deployment #' + deploymentId +
          (phase === 'running' ? ' is running.' : phase === 'failed' ? ' failed to deploy.' + detail : ' is being provisioned&hellip;') +
          '</div></div>';
        if (phase === 'running' || phase === 'failed') {
          loadDeployments();
          return;
        }
      } catch (e) {
        // Network hiccup mid-poll - keep trying rather than giving up on one blip.
      }
      if (attempts < maxAttempts) setTimeout(tick, 5000);
    }

    tick();
  }
</script>"""

    ready = "initDeployments();"

    html = (
        "<!DOCTYPE html>\n<html lang=\"en\">\n<head>\n<meta charset=\"UTF-8\">\n"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">\n"
        "<title>Deployments - Vela Admin</title>\n" + ds_assets + "\n</head>\n<body>\n"
        + body
        + "\n" + _SCRIPTS + "\n" + script
        + _boot_script("/admin/deployments", "Deployments", ready)
        + "\n</body>\n</html>"
    )
    return html


# =========================================================================
# Infrastructure - /admin/infrastructure
#
# Phase 2: migrated to the ds/* design system (see admin_overview_page /
# admin_models_page for the same local ds_assets pattern). Presentation
# only - every fetch below is unchanged.
#
# "Running instances" and the services table are built from
# /models/status + /deployments' replica counts, not the Kubernetes Pod
# API directly (no endpoint exposes individual Pod objects) - labeled
# accordingly rather than claiming pod-level precision. "Uptime" is
# derived from the most recent "deploy" event on /timeline (itself
# sourced from Prometheus process_start_time_seconds). Node CPU/memory
# come from /metrics-summary's node_cpu_percent/node_memory_*_gb. All
# three of these Prometheus-backed reads (and /deployments' Kubernetes
# read) already fail soft server-side - None/[] on an unreachable
# Prometheus or cluster, never a 500 - so what this page renders for
# "nothing came back" is purely a frontend/DS concern now.
# =========================================================================

@router.get("/admin/infrastructure", response_class=HTMLResponse)
def admin_infrastructure_page():
    ds_assets = (
        '<link rel="stylesheet" href="/static/css/ds/tokens.css?v=ds5">\n'
        '<link rel="stylesheet" href="/static/css/ds/base.css?v=ds5">\n'
        '<link rel="stylesheet" href="/static/css/ds/primitives.css?v=ds5">\n'
        '<link rel="stylesheet" href="/static/css/ds/shell.css?v=ds7">'
    )

    body = """
<div id="page-content" hidden>
  <div class="page-max">
    <div class="page-header">
      <div>
        <h1 class="page-title">Infrastructure</h1>
        <div class="page-description">Node resource usage and running services.</div>
      </div>
      <div class="page-actions">
        <button class="btn btn-secondary btn-sm" id="refresh-btn" type="button">Refresh</button>
      </div>
    </div>

    <div class="grid-2" style="margin-bottom:var(--space-4)">
      <div class="panel">
        <div class="meter-label" id="cpu-label"><span>Node CPU usage</span><span class="meter-value" id="cpu-val">&mdash;</span></div>
        <div class="meter-track"><div class="meter-fill" id="cpu-fill" style="width:0%"></div></div>
      </div>
      <div class="panel">
        <div class="meter-label" id="mem-label"><span>Node memory usage</span><span class="meter-value" id="mem-val">&mdash;</span></div>
        <div class="meter-track"><div class="meter-fill" id="mem-fill" style="width:0%"></div></div>
      </div>
    </div>

    <div class="metric-strip" style="margin-bottom:var(--space-5)">
      <div class="metric-strip-item"><div class="metric-strip-value" id="pod-count">&mdash;</div><div class="metric-strip-label">Running instances</div></div>
      <div class="metric-strip-item"><div class="metric-strip-value" id="uptime-val" style="font-size:var(--text-md)">&mdash;</div><div class="metric-strip-label">Uptime since last deploy</div></div>
    </div>

    <div class="section-label">Services</div>
    <div class="table-wrap">
      <table class="table" style="min-width:520px">
        <thead><tr><th>Name</th><th>Type</th><th>Status</th><th>Replicas</th></tr></thead>
        <tbody id="services-body"></tbody>
      </table>
    </div>
  </div>
</div>
<div id="loading-root" style="min-height:100vh;display:flex;align-items:center;justify-content:center;color:var(--text-muted);font-size:var(--text-sm)">Loading&hellip;</div>
"""

    script = """
<script>
  // variant is null for a normal reading (no color - ds rule: a healthy
  // value is simply not colored) or 'warning'/'error' past a threshold -
  // applied to both the fill AND the label/value together, never just
  // the bar, so the read-out text itself carries the same signal.
  function setMeter(prefix, pct, label, variant) {
    const fill = document.getElementById(prefix + '-fill');
    const val = document.getElementById(prefix + '-val');
    const labelEl = document.getElementById(prefix + '-label');
    if (fill) {
      fill.style.width = Math.min(100, Math.max(0, pct)) + '%';
      fill.className = 'meter-fill' + (variant ? ' is-' + variant : '');
    }
    if (val) val.textContent = label;
    if (labelEl) labelEl.className = 'meter-label' + (variant ? ' is-' + variant : '');
  }

  // Prometheus having nothing for this reading (unreachable locally, or
  // a fresh node with no scrape yet) is NOT the same fact as "0% usage" -
  // showing a fabricated 0% bar would read as "measured and idle" when
  // it's actually "never measured". Same honesty rule as Model Health's
  // "No telemetry yet" panel, just sized for an inline meter instead of
  // a full panel.
  function setMeterUnavailable(prefix) {
    const fill = document.getElementById(prefix + '-fill');
    const val = document.getElementById(prefix + '-val');
    const labelEl = document.getElementById(prefix + '-label');
    if (fill) { fill.style.width = '0%'; fill.className = 'meter-fill'; }
    if (val) val.textContent = 'Not instrumented';
    if (labelEl) labelEl.className = 'meter-label';
  }

  function fmtN(n, dec) { return (n == null || isNaN(n)) ? '—' : Number(n).toFixed(dec); }

  function meterVariant(pct) { return pct > 85 ? 'error' : pct > 65 ? 'warning' : null; }

  async function loadMetrics() {
    try {
      const d = await Api.get('/metrics-summary');

      if (d.node_cpu_percent == null) {
        setMeterUnavailable('cpu');
      } else {
        const cpu = Math.round(d.node_cpu_percent);
        setMeter('cpu', cpu, cpu + '%', meterVariant(cpu));
      }

      if (d.node_memory_used_gb == null || d.node_memory_total_gb == null || d.node_memory_total_gb <= 0) {
        setMeterUnavailable('mem');
      } else {
        const mu = d.node_memory_used_gb;
        const mt = d.node_memory_total_gb;
        const mp = Math.round((mu / mt) * 100);
        setMeter('mem', mp, fmtN(mu, 1) + 'GB / ' + fmtN(mt, 1) + 'GB (' + mp + '%)', meterVariant(mp));
      }
    } catch (e) {
      // /metrics-summary itself fails soft server-side (see comment
      // above) - this only fires on a real network-level failure, and
      // never shows the raw error, just the same honest unavailable
      // state as "Prometheus had nothing".
      console.error('Infrastructure: loadMetrics failed', e);
      setMeterUnavailable('cpu');
      setMeterUnavailable('mem');
      UI.toast('Could not load node metrics.', 'danger');
    }
  }

  async function loadServices() {
    const body = document.getElementById('services-body');
    body.innerHTML = UI.skeletonRows(4, 3);
    try {
      const deployments = await Api.get('/deployments');
      let runningInstances = 0;
      const rows = deployments.map(d => {
        runningInstances += d.ready || 0;
        return { name: d.name, type: 'Platform deployment', status: d.status, replicas: d.ready + '/' + d.desired };
      });
      document.getElementById('pod-count').textContent = runningInstances;
      if (!rows.length) {
        body.innerHTML = '<tr><td colspan="4">' + UI.emptyState('No services running', 'Deployed models will appear here.') + '</td></tr>';
        return;
      }
      body.innerHTML = rows.map(r =>
        '<tr><td class="mono">' + UI.escapeHtml(r.name) + '</td><td class="text-secondary">' + r.type + '</td><td>' + UI.statusBadge(r.status) + '</td><td class="text-secondary">' + r.replicas + '</td></tr>'
      ).join('');
    } catch (e) {
      body.innerHTML = '<tr><td colspan="4">' + UI.errorState(e.message, loadServices) + '</td></tr>';
      document.getElementById('pod-count').textContent = '—';
    }
  }

  async function loadUptime() {
    const el = document.getElementById('uptime-val');
    try {
      const events = await Api.get('/timeline?window_minutes=1440');
      const deploys = events.filter(e => e.type === 'deploy');
      if (!deploys.length) { el.textContent = 'No deploy events'; return; }
      const last = deploys[deploys.length - 1];
      const seconds = Math.max(0, Date.now() / 1000 - last.timestamp);
      const hours = Math.floor(seconds / 3600);
      el.textContent = hours < 1 ? Math.floor(seconds / 60) + 'm' : hours < 48 ? hours + 'h' : Math.floor(hours / 24) + 'd';
    } catch (e) {
      // Same rule as elsewhere on this page - /timeline already fails
      // soft server-side, so this is a real network failure at best;
      // never the raw error, just a calm "can't tell right now".
      console.error('Infrastructure: loadUptime failed', e);
      el.textContent = 'Unavailable';
    }
  }

  function initInfrastructure() {
    const refreshBtn = document.getElementById('refresh-btn');
    if (refreshBtn) refreshBtn.addEventListener('click', () => { loadMetrics(); loadServices(); loadUptime(); });
    loadMetrics();
    loadServices();
    loadUptime();
  }
</script>"""

    ready = "initInfrastructure();"

    html = (
        "<!DOCTYPE html>\n<html lang=\"en\">\n<head>\n<meta charset=\"UTF-8\">\n"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">\n"
        "<title>Infrastructure - Vela Admin</title>\n" + ds_assets + "\n</head>\n<body>\n"
        + body
        + "\n" + _SCRIPTS + "\n" + script
        + _boot_script("/admin/infrastructure", "Infrastructure", ready)
        + "\n</body>\n</html>"
    )
    return html


# =========================================================================
# API Keys - /admin/api-keys
#
# Phase 2: migrated to the ds/* design system (see admin_teams_page for
# the reference pattern - creation in a slide-over, confirmations as
# modals, shared openSlideover/closeSlideoverChrome helper). Presentation
# only: every loader and CRUD call below (workspaces + per-workspace key
# loads, create key, revoke key) is unchanged.
#
# GET /workspaces returns only workspaces the CALLING user belongs to -
# there is no platform-wide "list every workspace" endpoint, and
# is_admin doesn't grant broader visibility there. This shows the
# admin's own workspace memberships (typically ones bootstrapped from
# the Teams page), not necessarily every workspace on the platform.
#
# Key-reveal: POST .../api-keys returns the raw key exactly once, at
# creation - it's never stored anywhere retrievable again (list_api_keys
# in auth.py only ever returns key_prefix). The New key slide-over's body
# swaps in place from the create form to a reveal state on success
# (renderKeyReveal()) rather than opening a second modal on top of it -
# one surface, no overlay-on-overlay focus handoff to get right. The
# table only ever shows that same prefix, masked with an ellipsis - there
# is no key suffix available to show instead (and there shouldn't be:
# deriving one would mean storing the plaintext key, which is exactly the
# thing this design avoids). No Status column - list_api_keys only ever
# returns active keys (revoked ones are filtered server-side), so every
# row would say the same thing; that's noise, not signal.
# =========================================================================

@router.get("/admin/api-keys", response_class=HTMLResponse)
def admin_api_keys_page():
    ds_assets = (
        '<link rel="stylesheet" href="/static/css/ds/tokens.css?v=ds5">\n'
        '<link rel="stylesheet" href="/static/css/ds/base.css?v=ds5">\n'
        '<link rel="stylesheet" href="/static/css/ds/primitives.css?v=ds5">\n'
        '<link rel="stylesheet" href="/static/css/ds/shell.css?v=ds7">'
    )

    body = """
<div id="page-content" hidden>
  <div class="page-max">
    <div class="page-header">
      <div>
        <h1 class="page-title">API Keys</h1>
        <div class="page-description">Workspaces you belong to and their keys. There's no platform-wide workspace list in the API &mdash; this shows workspaces your admin account is a member of.</div>
      </div>
      <div class="page-actions">
        <button class="btn btn-secondary btn-sm" id="refresh-btn" type="button">Refresh</button>
        <button class="btn btn-primary btn-sm" id="new-key-btn" type="button">New key</button>
      </div>
    </div>

    <div class="toolbar">
      <span class="input-group" style="flex:1 1 220px">
        <svg class="input-icon" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5"><circle cx="7" cy="7" r="4.5"/><path d="m11 11 3 3"/></svg>
        <input class="input" id="keys-filter" type="text" placeholder="Filter by name, workspace, team or model" autocomplete="off" style="flex:1;min-width:0">
      </span>
      <span class="toolbar-spacer"></span>
      <span class="text-muted" id="keys-count" style="font-size:var(--text-xs);flex-shrink:0"></span>
    </div>
    <div class="table-wrap">
      <table class="table" style="min-width:680px">
        <thead><tr><th>Name</th><th>Key</th><th>Scope</th><th>Created</th><th>Last used</th><th class="num">Actions</th></tr></thead>
        <tbody id="keys-body"></tbody>
      </table>
    </div>
  </div>

  <div class="slideover-overlay" id="new-key-panel" hidden>
  <div class="slideover" role="dialog" aria-modal="true" aria-labelledby="new-key-panel-title">
    <div class="slideover-header">
      <div class="slideover-title" id="new-key-panel-title">New key</div>
      <button class="btn btn-ghost btn-sm btn-icon" id="close-new-key-panel" type="button" aria-label="Close">&#10005;</button>
    </div>
    <div class="slideover-body" id="new-key-body"></div>
  </div>
  </div>
</div>
<div id="loading-root" style="min-height:100vh;display:flex;align-items:center;justify-content:center;color:var(--text-muted);font-size:var(--text-sm)">Loading&hellip;</div>
"""

    script = """
<script>
  let cachedWorkspaces = [];
  let cachedRows = [];

  function initApiKeys() {
    const refreshBtn = document.getElementById('refresh-btn');
    if (refreshBtn) refreshBtn.addEventListener('click', () => loadWorkspaces());
    const filterInput = document.getElementById('keys-filter');
    if (filterInput) filterInput.addEventListener('input', renderKeysTable);
    wireNewKeyPanel();
    loadWorkspaces();
  }

  async function loadWorkspaces() {
    const body = document.getElementById('keys-body');
    body.innerHTML = UI.skeletonRows(6, 5);
    try {
      cachedWorkspaces = await Api.get('/workspaces');
      if (!cachedWorkspaces.length) {
        cachedRows = [];
        body.innerHTML = '<tr><td colspan="6">' + UI.emptyState('No workspaces yet', 'Create a team from the Teams page to bootstrap your first workspace.') + '</td></tr>';
        const countEl = document.getElementById('keys-count');
        if (countEl) countEl.textContent = '';
        return;
      }
      const perWorkspace = await Promise.allSettled(cachedWorkspaces.map(ws => Api.get('/workspaces/' + ws.id + '/api-keys')));
      const rows = [];
      perWorkspace.forEach((r, i) => {
        if (r.status !== 'fulfilled') return;
        r.value.forEach(k => rows.push(Object.assign({}, k, { ws_id: cachedWorkspaces[i].id, ws_name: cachedWorkspaces[i].name })));
      });
      cachedRows = rows;
      renderKeysTable();
    } catch (e) {
      cachedRows = [];
      body.innerHTML = '<tr><td colspan="6">' + UI.errorState(e.message, loadWorkspaces) + '</td></tr>';
      const countEl = document.getElementById('keys-count');
      if (countEl) countEl.textContent = '';
    }
  }

  // Workspace is always shown; team/model only appear when the key is
  // further narrowed (see auth.py's create/list handlers) - already
  // fetched in list_api_keys' response, just not previously displayed.
  function scopeParts(k) {
    const parts = [k.ws_name];
    if (k.team_name) parts.push('Team: ' + k.team_name);
    if (k.model_name || k.deployment_name) parts.push('Model: ' + (k.model_name || k.deployment_name));
    return parts;
  }

  // Client-side only: filters the already-loaded cachedRows, same
  // pattern as the Teams/Users filters.
  function renderKeysTable() {
    const body = document.getElementById('keys-body');
    const countEl = document.getElementById('keys-count');
    const q = (document.getElementById('keys-filter').value || '').trim().toLowerCase();

    if (!cachedRows.length) {
      body.innerHTML = '<tr><td colspan="6">' + UI.emptyState('No keys yet', 'Generate one with the button above.') + '</td></tr>';
      if (countEl) countEl.textContent = '';
      return;
    }

    const rows = cachedRows.filter(k => {
      if (!q) return true;
      return (k.name || '').toLowerCase().includes(q) || scopeParts(k).join(' ').toLowerCase().includes(q);
    });

    if (countEl) {
      countEl.textContent = q
        ? rows.length + ' of ' + cachedRows.length
        : cachedRows.length + (cachedRows.length === 1 ? ' key' : ' keys');
    }

    if (!rows.length) {
      body.innerHTML = '<tr><td colspan="6">' + UI.emptyState('No matches', 'No key matches that filter.') + '</td></tr>';
      return;
    }

    body.innerHTML = rows.map(renderKeyRow).join('');
    body.querySelectorAll('[data-revoke-key]').forEach(btn => {
      btn.addEventListener('click', () => {
        const parts = btn.dataset.revokeKey.split(':');
        confirmRevokeKey(parts[0], parts[1], btn.dataset.name);
      });
    });
  }

  // Never the full key - only ever the prefix this list endpoint
  // returns, masked with an ellipsis (see comment above the route).
  // Team/model scope reads as a neutral badge, same as role/team labels
  // on the Users/Teams tables - identity, not status, so no color.
  function renderKeyRow(k) {
    const parts = scopeParts(k);
    const scopeHtml = '<span class="text-secondary">' + UI.escapeHtml(parts[0]) + '</span>' +
      parts.slice(1).map(p => ' ' + UI.badge(p, 'neutral')).join('');
    return '<tr>' +
      '<td>' + UI.escapeHtml(k.name) + '</td>' +
      '<td class="mono">' + UI.escapeHtml(k.prefix) + '&hellip;</td>' +
      '<td>' + scopeHtml + '</td>' +
      '<td class="text-secondary">' + UI.fmtDate(k.created_at) + '</td>' +
      '<td class="text-secondary">' + (k.last_used_at ? UI.timeAgo(k.last_used_at) : 'Never') + '</td>' +
      '<td class="num"><button class="link-action link-danger" data-revoke-key="' + k.ws_id + ':' + k.id + '" data-name="' + UI.escapeHtml(k.name) + '" type="button">Revoke</button></td>' +
      '</tr>';
  }

  // Irreversible - there is no un-revoke endpoint, and anything using the
  // key breaks immediately - same class as Delete User, so type-to-
  // confirm rather than the lightweight Cancel/Confirm Teams' reversible
  // actions get. Underlying call unchanged.
  function confirmRevokeKey(wsId, keyId, name) {
    const overlay = UI.openModal({
      title: 'Revoke ' + name,
      bodyHtml: `
        <div class="alert alert-danger" style="margin-bottom:var(--space-3)">
          <div><div class="alert-title">This cannot be undone</div><div>Anything using this key will stop working immediately. Type the key name to confirm.</div></div>
        </div>
        <div class="field">
          <label class="field-label" for="revoke-key-confirm-name">Key name</label>
          <input class="input" id="revoke-key-confirm-name" placeholder="${UI.escapeHtml(name)}">
        </div>
        <div class="field-error" id="revoke-key-confirm-error" role="alert"></div>
      `,
      footerHtml: `<button class="btn btn-ghost" id="revoke-key-cancel" type="button">Cancel</button>
                   <button class="btn btn-danger" id="revoke-key-confirm" type="button" disabled>Revoke</button>`,
    });
    const input = overlay.querySelector('#revoke-key-confirm-name');
    const confirmBtn = overlay.querySelector('#revoke-key-confirm');
    const errorEl = overlay.querySelector('#revoke-key-confirm-error');

    input.addEventListener('input', () => {
      confirmBtn.disabled = input.value !== name;
    });
    overlay.querySelector('#revoke-key-cancel').addEventListener('click', UI.closeModal);

    confirmBtn.addEventListener('click', async () => {
      confirmBtn.disabled = true;
      confirmBtn.textContent = 'Revoking…';
      errorEl.textContent = '';
      try {
        await Api.del('/workspaces/' + wsId + '/api-keys/' + keyId);
        UI.closeModal();
        UI.toast('Key revoked', 'success');
        loadWorkspaces();
      } catch (e) {
        errorEl.textContent = e.message || 'Could not revoke key.';
        confirmBtn.disabled = false;
        confirmBtn.textContent = 'Revoke';
      }
    });
  }

  // ================================================================
  // New key slide-over - the form and the one-time reveal are two
  // states of the SAME panel (renderNewKeyForm() / renderKeyReveal()
  // swap #new-key-body's content in place) rather than a second modal
  // opened on top of the first: one surface, one focus trap, and the
  // reveal can't be reached without having just gone through the form.
  // Reopening the panel always starts back at the form (openNewKeyPanel
  // re-renders it unconditionally), so a finished reveal never lingers.
  // ================================================================

  function renderNewKeyForm() {
    const titleEl = document.getElementById('new-key-panel-title');
    const body = document.getElementById('new-key-body');
    if (titleEl) titleEl.textContent = 'New key';
    const wsOptions = cachedWorkspaces.map(ws => '<option value="' + ws.id + '">' + UI.escapeHtml(ws.name) + '</option>').join('');
    body.innerHTML = `
      <form class="form" id="new-key-form" novalidate>
        ${cachedWorkspaces.length > 1 ? `<div class="field"><label class="field-label" for="nk-ws">Workspace</label><select class="select" id="nk-ws">${wsOptions}</select></div>` : ''}
        <div class="field"><label class="field-label" for="nk-name">Key name</label><input class="input" id="nk-name" placeholder="e.g. production, ci-cd" required></div>
        <div class="field-error" id="nk-error" role="alert"></div>
        <button class="btn btn-primary btn-block" type="submit" id="nk-submit">Generate key</button>
      </form>`;

    document.getElementById('new-key-form').addEventListener('submit', async (e) => {
      e.preventDefault();
      const wsSel = document.getElementById('nk-ws');
      const wsId = wsSel ? wsSel.value : (cachedWorkspaces[0] && cachedWorkspaces[0].id);
      const errorEl = document.getElementById('nk-error');
      const submitBtn = document.getElementById('nk-submit');
      const name = document.getElementById('nk-name').value.trim();
      if (!name) { errorEl.textContent = 'Give the key a name.'; return; }
      if (wsId == null) { errorEl.textContent = 'No workspace to create this key in.'; return; }
      submitBtn.disabled = true;
      submitBtn.textContent = 'Generating…';
      errorEl.textContent = '';
      try {
        const result = await Api.post('/workspaces/' + wsId + '/api-keys', { name });
        renderKeyReveal(result);
        loadWorkspaces();
      } catch (err) {
        errorEl.textContent = err.message || 'Could not create key.';
        submitBtn.disabled = false;
        submitBtn.textContent = 'Generate key';
      }
    });
  }

  // The key in result.key is the only time it's ever available - see
  // the route comment above. Copy uses UI.copyText's clipboard-with-
  // execCommand-fallback (this backend is served over plain HTTP, where
  // navigator.clipboard is commonly just undefined) and always shows
  // whether it actually worked, never a silent no-op.
  function renderKeyReveal(result) {
    const titleEl = document.getElementById('new-key-panel-title');
    const body = document.getElementById('new-key-body');
    if (titleEl) titleEl.textContent = 'Copy your API key';
    body.innerHTML = `
      <div class="alert alert-warning" style="margin-bottom:var(--space-3)">
        <div><div class="alert-title">Shown once</div>This key will not be shown again once you close this panel &mdash; copy it now.</div></div>
      </div>
      <div class="field">
        <label class="field-label">${UI.escapeHtml(result.name)}</label>
        <input class="input mono" id="raw-key" value="${UI.escapeHtml(result.key)}" readonly style="font-size:var(--text-xs)">
      </div>
      <button class="btn btn-secondary btn-block" id="rk-copy" type="button" style="margin-bottom:var(--space-2)">Copy to clipboard</button>
      <button class="btn btn-primary btn-block" id="rk-done" type="button">Done</button>
    `;
    document.getElementById('rk-done').addEventListener('click', closeNewKeyPanel);
    document.getElementById('rk-copy').addEventListener('click', async () => {
      const input = document.getElementById('raw-key');
      const ok = await UI.copyText(input.value);
      if (ok) {
        UI.toast('Copied to clipboard', 'success');
      } else {
        input.select();
        UI.toast('Could not copy automatically - key is selected, press Ctrl/Cmd+C', 'danger');
      }
    });
  }

  function openNewKeyPanel() {
    renderNewKeyForm();
    openSlideover('new-key-panel', '#nk-name', closeNewKeyPanel);
  }

  function closeNewKeyPanel() {
    closeSlideoverChrome('new-key-panel');
  }

  function wireNewKeyPanel() {
    const panel = document.getElementById('new-key-panel');
    const openBtn = document.getElementById('new-key-btn');
    const closeBtn = document.getElementById('close-new-key-panel');
    if (!panel || !openBtn) return;
    openBtn.addEventListener('click', openNewKeyPanel);
    closeBtn.addEventListener('click', closeNewKeyPanel);
    panel.addEventListener('click', (e) => { if (e.target === panel) closeNewKeyPanel(); });
  }

  // ================================================================
  // Shared slide-over chrome (open/close/focus-trap) - same helper as
  // admin_teams_page, duplicated here since each route's <script> is
  // self-contained (no shared ds.js module yet).
  // ================================================================

  const slideoverState = {};

  function openSlideover(id, focusSelector, onClose) {
    const panel = document.getElementById(id);
    if (!panel) return;
    const state = { returnFocus: document.activeElement };
    state.keydownHandler = (e) => {
      if (e.key === 'Escape') { onClose(); return; }
      if (e.key !== 'Tab') return;
      const focusables = Array.from(panel.querySelectorAll(
        'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled])'
      )).filter(el => el.offsetParent !== null);
      if (!focusables.length) return;
      const first = focusables[0], last = focusables[focusables.length - 1];
      if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
      else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
    };
    slideoverState[id] = state;
    panel.hidden = false;
    document.addEventListener('keydown', state.keydownHandler);
    const first = focusSelector ? panel.querySelector(focusSelector) : null;
    if (first) first.focus();
  }

  function closeSlideoverChrome(id) {
    const panel = document.getElementById(id);
    const state = slideoverState[id];
    if (!panel || panel.hidden) return;
    panel.hidden = true;
    if (state && state.keydownHandler) document.removeEventListener('keydown', state.keydownHandler);
    if (state && state.returnFocus && document.contains(state.returnFocus)) state.returnFocus.focus();
    delete slideoverState[id];
  }
</script>"""

    ready = "initApiKeys();"

    html = (
        "<!DOCTYPE html>\n<html lang=\"en\">\n<head>\n<meta charset=\"UTF-8\">\n"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">\n"
        "<title>API Keys - Vela Admin</title>\n" + ds_assets + "\n</head>\n<body>\n"
        + body
        + "\n" + _SCRIPTS + "\n" + script
        + _boot_script("/admin/api-keys", "API Keys", ready)
        + "\n</body>\n</html>"
    )
    return html
