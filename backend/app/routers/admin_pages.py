"""
Admin HTML pages (spec §7/§8): Overview, Users, Teams, Tickets.

These are separate from the JSON /admin/* API defined in main.py — note the
"-page" suffix on Users/Teams/Tickets, which avoids colliding with the
existing GET /admin/users, /admin/teams, /admin/tickets JSON routes
(Starlette matches routes in registration order; a same-path HTML page
would silently shadow or be shadowed by the JSON API). /admin itself has
no such collision, so the Overview page keeps the clean path.

Like the rest of this codebase, pages are raw HTML strings — no template
engine, no build step. Each page loads the shared design system + AppShell
from /static, then fetches its data client-side from the existing API.
"""

from fastapi import APIRouter
from fastapi.responses import HTMLResponse, RedirectResponse

from backend.app.routers._page_fragments import (
    CHART_JS_CDN, MONITORING_CSS, MONITORING_BODY, MONITORING_SCRIPTS_EXTRA,
    DRIFT_BODY, DRIFT_SCRIPTS_EXTRA,
    DOCS_BODY, DOCS_SCRIPTS_EXTRA,
    SETTINGS_BODY, SETTINGS_SCRIPTS_EXTRA,
)

router = APIRouter()

_ASSETS = """<link rel="stylesheet" href="/static/css/tokens.css?v=8">
<link rel="stylesheet" href="/static/css/base.css?v=8">
<link rel="stylesheet" href="/static/css/components.css?v=8">
<link rel="stylesheet" href="/static/css/shell.css?v=8">"""

_SCRIPTS = """<script src="/static/js/api.js?v=8"></script>
<script src="/static/js/shell.js?v=8"></script>
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
# Overview — /admin
# =========================================================================

@router.get("/admin", response_class=HTMLResponse)
def admin_overview_page():
    body = """
<div id="page-content" hidden>
  <div class="page-max">
    <div class="card-header" style="margin-bottom:var(--space-2)">
      <div>
        <h1 id="greeting" style="font-size:var(--text-lg)">Loading…</h1>
        <div id="platform-status" class="text-secondary" style="font-size:var(--text-sm);margin-top:2px"></div>
      </div>
    </div>

    <div class="metric-strip" id="metric-row" style="margin:var(--space-5) 0"></div>

    <div class="section-label">Model health</div>
    <div id="drift-banner"></div>
    <div class="table-wrap">
      <table class="table">
        <thead>
          <tr><th>Model</th><th>Task</th><th>Source</th><th>Status</th><th>Actions</th></tr>
        </thead>
        <tbody id="model-health-body">""" + "" + """</tbody>
      </table>
    </div>

    <div class="section-label">Recent tickets</div>
    <div id="recent-tickets-card"></div>
  </div>
</div>
<div class="auth-loading" id="loading-root">Loading…</div>
"""

    script = """
<script>
  function fmtPct(x) { return (x == null || isNaN(x)) ? '—' : (x * 100).toFixed(1) + '%'; }

  let overviewRows = [];
  let managementApiKey = '';
  let overviewUser = null;

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

    // Every model on the platform is a real Deployment row now — GET
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

  // A plain-text 3-column strip (spec) instead of a KPI card wall —
  // total running models, open tickets, and platform-wide drift, each
  // just a number + label separated by a divider.
  function stripItem(value, label, variant) {
    return '<div class="metric-strip-item"><div class="metric-strip-value' + (variant ? ' is-' + variant : '') + '">' + value + '</div><div class="metric-strip-label">' + label + '</div></div>';
  }

  function renderMetrics(tickets, rows, metrics) {
    const running = rows.filter(r => r.status === 'online' || r.status === 'running').length;
    const openTickets = tickets.filter(t => t.status === 'open' || t.status === 'investigating').length;
    document.getElementById('metric-row').innerHTML =
      stripItem(running + ' / ' + rows.length, 'Models running') +
      stripItem(openTickets, 'Open tickets', openTickets > 0 ? 'warning' : undefined) +
      stripItem(fmtPct(metrics.drift_score), 'Platform drift', (metrics.drift_score || 0) > 0.3 ? 'danger' : undefined);
  }

  // There's no per-model drift breakdown fetched on this page (that lives
  // on /admin/drift, one model at a time) — only a platform-wide
  // drift_score from /metrics-summary. Rather than invent a specific
  // model name for the banner, this reflects what's actually known: the
  // platform-wide figure crossing a threshold.
  function renderDriftBanner(metrics) {
    const el = document.getElementById('drift-banner');
    if ((metrics.drift_score || 0) <= 0.3) { el.innerHTML = ''; return; }
    el.innerHTML = '<div class="banner-strip is-warning">&#9888; Elevated drift detected across the platform (' +
      fmtPct(metrics.drift_score) + ' of tracked features) — <a href="/admin/drift">Investigate &rarr;</a></div>';
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
  // the Model Registry page — prompted for once, lazily, cached for the
  // rest of this page's lifetime.
  function ensureApiKey() {
    if (managementApiKey) return Promise.resolve(managementApiKey);
    return new Promise((resolve) => {
      const overlay = UI.openModal({
        title: 'API key required',
        bodyHtml: `
          <p class="text-secondary" style="font-size:var(--text-sm);margin-bottom:.75rem">An unscoped workspace API key is needed to manage models — see API Keys.</p>
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
        <div class="alert alert-danger" style="margin-bottom:.75rem">
          <div><div class="alert-title">This cannot be undone</div><div class="alert-body">This will remove the model and revoke all team access. Type the model name to confirm.</div></div>
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

  function renderRecentTickets(tickets) {
    const card = document.getElementById('recent-tickets-card');
    if (!tickets.length) {
      card.innerHTML = UI.emptyState('No tickets yet', 'Tickets filed by team members will appear here.');
      return;
    }
    const recent = tickets.slice(0, 5);
    card.innerHTML = recent.map(t =>
      '<div style="display:flex;justify-content:space-between;align-items:center;gap:.75rem;padding:.5rem 0;border-bottom:1px solid var(--color-border-subtle)">' +
      '<div style="min-width:0">' +
      '<div style="font-size:var(--text-sm);white-space:nowrap;overflow:hidden;text-overflow:ellipsis">' + UI.escapeHtml(t.title) + '</div>' +
      '<div class="text-muted" style="font-size:var(--text-xs)">' + UI.timeAgo(t.filed_at) + '</div>' +
      '</div>' +
      '<div style="flex-shrink:0">' + UI.severityBadge(t.severity) + '</div>' +
      '</div>'
    ).join('') + '<div style="margin-top:.75rem"><a href="/admin/tickets-page" class="link-secondary" style="font-size:var(--text-sm)">View all tickets &rarr;</a></div>';
  }
</script>"""

    ready = "loadOverview(user);"

    html = (
        "<!DOCTYPE html>\n<html lang=\"en\">\n<head>\n<meta charset=\"UTF-8\">\n"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">\n"
        "<title>Overview — Vela Admin</title>\n" + _ASSETS + "\n</head>\n<body>\n"
        + body
        + "\n" + _SCRIPTS + "\n" + script
        + _boot_script("/admin", "Overview", ready)
        + "\n</body>\n</html>"
    )
    return html


# =========================================================================
# Users — /admin/users-page
# =========================================================================

@router.get("/admin/users-page", response_class=HTMLResponse)
def admin_users_page():
    body = """
<div id="page-content" hidden>
  <div class="page-max">
    <div class="card-header">
      <h1 style="font-size:var(--text-lg)">Users</h1>
      <button class="btn btn-primary" id="new-user-btn" type="button">New user</button>
    </div>
    <div class="table-wrap">
      <table class="table">
        <thead>
          <tr><th>Username</th><th>Name</th><th>Role</th><th>Teams</th><th>Status</th><th>Created</th><th></th></tr>
        </thead>
        <tbody id="users-body">""" + "" + """</tbody>
      </table>
    </div>
  </div>
</div>
<div class="auth-loading" id="loading-root">Loading…</div>
"""

    script = """
<script>
  let currentUser = null;
  let cachedUsers = [];
  let cachedTeams = [];

  async function loadUsers() {
    const body = document.getElementById('users-body');
    body.innerHTML = UI.skeletonRows(7, 4);
    try {
      const [users, teams] = await Promise.all([Api.get('/admin/users'), Api.get('/admin/teams')]);
      cachedUsers = users;
      cachedTeams = teams;
      renderUsers();
    } catch (e) {
      body.innerHTML = '<tr><td colspan="7">' + UI.errorState(e.message, loadUsers) + '</td></tr>';
    }
  }

  function teamsForUser(userId) {
    const names = [];
    cachedTeams.forEach(t => {
      if ((t.members || []).some(m => m.user_id === userId)) names.push(t.name);
    });
    return names;
  }

  function renderUsers() {
    const body = document.getElementById('users-body');
    if (!cachedUsers.length) {
      body.innerHTML = '<tr><td colspan="7">' + UI.emptyState('No users yet', 'Create the first user to get started.') + '</td></tr>';
      return;
    }
    body.innerHTML = cachedUsers.map(u => {
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
        '<td>' + UI.badge(u.is_admin ? 'Admin' : 'Member', u.is_admin ? 'info' : 'neutral') + '</td>' +
        '<td>' + teamBadges + '</td>' +
        '<td>' + UI.statusBadge(u.is_active ? 'active' : 'inactive') + (u.force_password_change ? ' ' + UI.statusDot('Pending first login', 'warning') : '') + '</td>' +
        '<td class="text-secondary">' + UI.fmtDate(u.created_at) + '</td>' +
        '<td style="text-align:right">' + action + '</td>' +
        '</tr>';
    }).join('');

    body.querySelectorAll('[data-deactivate]').forEach(btn => {
      btn.addEventListener('click', () => deactivateUser(btn.dataset.deactivate, btn.dataset.username));
    });
    body.querySelectorAll('[data-reactivate]').forEach(btn => {
      btn.addEventListener('click', () => reactivateUser(btn.dataset.reactivate, btn.dataset.username));
    });
    body.querySelectorAll('[data-delete]').forEach(btn => {
      btn.addEventListener('click', () => confirmDeleteUser(btn.dataset.delete, btn.dataset.username));
    });
  }

  async function deactivateUser(id, username) {
    if (!confirm('Deactivate ' + username + '? They will no longer be able to log in.')) return;
    try {
      await Api.patch('/admin/users/' + id + '/deactivate');
      UI.toast(username + ' deactivated', 'success');
      loadUsers();
    } catch (e) {
      UI.toast(e.message || 'Could not deactivate user', 'danger');
    }
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
        <div class="alert alert-danger" style="margin-bottom:.75rem">
          <div><div class="alert-title">This cannot be undone</div><div class="alert-body">This will permanently delete the user and all their data. Type the username to confirm.</div></div>
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

  function openNewUserModal() {
    const overlay = UI.openModal({
      title: 'New user',
      bodyHtml: `
        <form id="new-user-form" novalidate>
          <div class="field"><label class="field-label" for="nu-username">Username</label><input class="input" id="nu-username" required></div>
          <div class="field"><label class="field-label" for="nu-name">Full name</label><input class="input" id="nu-name" required></div>
          <div class="field"><label class="field-label" for="nu-password">Temporary password</label><input class="input" type="password" id="nu-password" required minlength="6"></div>
          <div class="checkbox-row" style="margin-bottom:.5rem"><input type="checkbox" id="nu-admin"><label for="nu-admin">Grant admin access</label></div>
          <div class="checkbox-row" style="margin-bottom:.5rem"><input type="checkbox" id="nu-force" checked><label for="nu-force">Require password change at first login</label></div>
          <div class="field-error" id="nu-error" role="alert"></div>
        </form>`,
      footerHtml: `<button class="btn btn-ghost" id="nu-cancel" type="button">Cancel</button>
                   <button class="btn btn-primary" id="nu-submit" type="submit" form="new-user-form">Create user</button>`,
    });
    overlay.querySelector('#nu-cancel').addEventListener('click', UI.closeModal);
    overlay.querySelector('#new-user-form').addEventListener('submit', async (e) => {
      e.preventDefault();
      const errorEl = overlay.querySelector('#nu-error');
      const username = overlay.querySelector('#nu-username').value.trim();
      const name = overlay.querySelector('#nu-name').value.trim();
      const password = overlay.querySelector('#nu-password').value;
      const is_admin = overlay.querySelector('#nu-admin').checked;
      const force_password_change = overlay.querySelector('#nu-force').checked;
      if (!username || !name || password.length < 6) {
        errorEl.textContent = 'Fill in all fields — password needs at least 6 characters.';
        return;
      }
      try {
        await Api.post('/admin/users', { username, name, password, is_admin, force_password_change });
        UI.toast('User ' + username + ' created', 'success');
        UI.closeModal();
        loadUsers();
      } catch (err) {
        errorEl.textContent = err.message || 'Could not create user.';
      }
    });
  }

  document.getElementById('new-user-btn').addEventListener('click', openNewUserModal);
</script>"""

    ready = "currentUser = user; loadUsers();"

    html = (
        "<!DOCTYPE html>\n<html lang=\"en\">\n<head>\n<meta charset=\"UTF-8\">\n"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">\n"
        "<title>Users — Vela Admin</title>\n" + _ASSETS + "\n</head>\n<body>\n"
        + body
        + "\n" + _SCRIPTS + "\n" + script
        + _boot_script("/admin/users-page", "Users", ready)
        + "\n</body>\n</html>"
    )
    return html


# =========================================================================
# Teams — /admin/teams-page
# =========================================================================

@router.get("/admin/teams-page", response_class=HTMLResponse)
def admin_teams_page():
    body = """
<div id="page-content" hidden>
  <div class="page-max">
    <div class="card-header">
      <h1 style="font-size:var(--text-lg)">Teams</h1>
      <button class="btn btn-primary" id="new-team-btn" type="button">New team</button>
    </div>
    <div id="teams-list"></div>
  </div>
</div>
<div class="auth-loading" id="loading-root">Loading…</div>
"""

    script = """
<script>
  let cachedUsers = [];
  let cachedTeams = [];
  let cachedDeployments = [];
  let workspaceId = null;

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

  async function loadTeams() {
    const list = document.getElementById('teams-list');
    list.innerHTML = '<div class="card"><span class="skeleton skeleton-text" style="display:block;max-width:220px">&nbsp;</span></div>';
    try {
      const [teams, users, deployments] = await Promise.all([
        Api.get('/admin/teams'), Api.get('/admin/users'), Api.get('/admin/deployment-registry')
      ]);
      cachedTeams = teams;
      cachedUsers = users;
      cachedDeployments = deployments;
      renderTeams();
    } catch (e) {
      list.innerHTML = UI.errorState(e.message, loadTeams);
    }
  }

  function renderTeams() {
    const list = document.getElementById('teams-list');
    if (!cachedTeams.length) {
      list.innerHTML = '<div class="card">' + UI.emptyState('No teams yet', 'Create a team to start assigning members and model access.') + '</div>';
      return;
    }
    list.innerHTML = cachedTeams.map(renderTeamCard).join('');
    cachedTeams.forEach(t => wireTeamCard(t));
  }

  function renderTeamCard(t) {
    const memberIds = new Set((t.members || []).map(m => m.user_id));
    const memberCount = (t.members || []).length;
    const memberRows = memberCount
      ? t.members.map(m =>
          '<div style="display:flex;justify-content:space-between;align-items:center;padding:.3rem 0">' +
          '<span style="font-size:var(--text-sm)">' + UI.escapeHtml(m.name || m.email || ('User #' + m.user_id)) +
          (m.role === 'lead' ? ' <span class="text-muted" style="font-size:var(--text-xs)">(lead)</span>' : '') + '</span>' +
          '<button class="link-action" data-remove-member="' + t.id + ':' + m.user_id + '" type="button">Remove</button>' +
          '</div>'
        ).join('')
      : '<div class="text-muted" style="font-size:var(--text-sm);padding:.3rem 0">No members yet</div>';

    const availableUsers = cachedUsers.filter(u => u.is_active && !memberIds.has(u.id));
    const userOptions = availableUsers.map(u => '<option value="' + u.id + '">' + UI.escapeHtml(u.name) + ' (' + UI.escapeHtml(u.username) + ')</option>').join('');

    const perms = t.permissions || [];
    const modelCount = perms.length;
    const permRows = modelCount
      ? perms.map(p =>
          '<div style="display:flex;justify-content:space-between;align-items:center;padding:.3rem 0">' +
          '<span style="font-size:var(--text-sm)">' + UI.escapeHtml(p.model_name || p.deployment_name || ('Deployment #' + p.deployment_id)) +
          '<span class="text-muted" style="font-size:var(--text-xs)">' + (p.can_predict ? ' &middot; predict' : '') + (p.can_view_metrics ? ' &middot; view metrics' : '') + '</span></span>' +
          '<button class="link-action link-danger" data-revoke-perm="' + t.id + ':' + p.deployment_id + '" type="button">Revoke</button>' +
          '</div>'
        ).join('')
      : '<div class="text-muted" style="font-size:var(--text-sm);padding:.3rem 0">No model access granted yet</div>';

    // deployment_id is a real FK into the deployments table — GET
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
        '<div style="display:flex;gap:.5rem;margin-top:.5rem;flex-wrap:wrap;align-items:center">' +
        '<select class="select" data-add-deployment="' + t.id + '" style="flex:2;min-width:160px">' + deploymentOptions + '</select>' +
        '<label class="checkbox-row"><input type="checkbox" data-can-predict="' + t.id + '" checked> Can predict</label>' +
        '<button class="btn btn-secondary btn-sm" data-grant-access="' + t.id + '" type="button">Add</button>' +
        '</div>';
    } else if (cachedDeployments.length) {
      addModelRow = '<div class="text-muted" style="font-size:var(--text-xs);margin-top:.5rem">All available models already granted</div>';
    } else {
      addModelRow = '<div class="text-muted" style="font-size:var(--text-xs);margin-top:.5rem">No models deployed yet</div>';
    }

    return '<div class="card" style="margin-bottom:var(--space-3)" data-team-card="' + t.id + '">' +
      '<div class="card-title" style="font-size:var(--text-lg)">' + UI.escapeHtml(t.name) + '</div>' +
      '<div class="card-subtitle">' + (t.description ? UI.escapeHtml(t.description) + ' &middot; ' : '') +
      memberCount + ' member' + (memberCount === 1 ? '' : 's') + ' &middot; ' + modelCount + ' model' + (modelCount === 1 ? '' : 's') + '</div>' +
      '<div class="grid-2" style="margin-top:var(--space-4)">' +
      '<div><div class="section-label" style="margin-top:0">Members</div>' + memberRows +
      (availableUsers.length ? (
        '<div style="display:flex;gap:.5rem;margin-top:.5rem;flex-wrap:wrap">' +
        '<select class="select" data-add-user="' + t.id + '" style="flex:2;min-width:120px">' + userOptions + '</select>' +
        '<select class="select" data-add-role="' + t.id + '" style="flex:1;min-width:90px"><option value="member">Member</option><option value="lead">Lead</option></select>' +
        '<button class="btn btn-secondary btn-sm" data-add-member="' + t.id + '" type="button">Add</button>' +
        '</div>'
      ) : '') + '</div>' +
      '<div><div class="section-label" style="margin-top:0">Models</div>' + permRows + addModelRow + '</div>' +
      '</div></div>';
  }

  function wireTeamCard(t) {
    const card = document.querySelector('[data-team-card="' + t.id + '"]');
    if (!card) return;
    card.querySelectorAll('[data-remove-member]').forEach(btn => {
      btn.addEventListener('click', () => {
        const [teamId, userId] = btn.dataset.removeMember.split(':');
        removeMember(teamId, userId);
      });
    });
    const addBtn = card.querySelector('[data-add-member="' + t.id + '"]');
    if (addBtn) addBtn.addEventListener('click', () => {
      const userSel = card.querySelector('[data-add-user="' + t.id + '"]');
      const roleSel = card.querySelector('[data-add-role="' + t.id + '"]');
      if (userSel && userSel.value) addMember(t.id, userSel.value, roleSel.value);
    });
    card.querySelectorAll('[data-revoke-perm]').forEach(btn => {
      btn.addEventListener('click', () => {
        const [teamId, deploymentId] = btn.dataset.revokePerm.split(':');
        revokeAccess(teamId, deploymentId);
      });
    });
    const grantBtn = card.querySelector('[data-grant-access="' + t.id + '"]');
    if (grantBtn) grantBtn.addEventListener('click', () => {
      const depSel = card.querySelector('[data-add-deployment="' + t.id + '"]');
      const predictChk = card.querySelector('[data-can-predict="' + t.id + '"]');
      if (depSel && depSel.value) grantAccess(t.id, depSel.value, predictChk.checked, false);
    });
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

  async function revokeAccess(teamId, deploymentId) {
    if (!confirm("Revoke this team's access to this model?")) return;
    try {
      await Api.del('/teams/' + teamId + '/permissions/' + deploymentId);
      UI.toast('Access revoked', 'success');
      loadTeams();
    } catch (e) {
      UI.toast(e.message || 'Could not revoke access', 'danger');
    }
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

  async function removeMember(teamId, userId) {
    if (!confirm('Remove this member from the team?')) return;
    try {
      await Api.del('/admin/teams/' + teamId + '/users/' + userId);
      UI.toast('Member removed', 'success');
      loadTeams();
    } catch (e) {
      UI.toast(e.message || 'Could not remove member', 'danger');
    }
  }

  function openNewTeamModal() {
    const overlay = UI.openModal({
      title: 'New team',
      bodyHtml: `
        <form id="new-team-form" novalidate>
          <div class="field"><label class="field-label" for="nt-name">Team name</label><input class="input" id="nt-name" required></div>
          <div class="field"><label class="field-label" for="nt-desc">Description (optional)</label><textarea class="textarea" id="nt-desc" rows="2"></textarea></div>
          <div class="field-error" id="nt-error" role="alert"></div>
        </form>`,
      footerHtml: `<button class="btn btn-ghost" id="nt-cancel" type="button">Cancel</button>
                   <button class="btn btn-primary" id="nt-submit" type="submit" form="new-team-form">Create team</button>`,
    });
    overlay.querySelector('#nt-cancel').addEventListener('click', UI.closeModal);
    overlay.querySelector('#new-team-form').addEventListener('submit', async (e) => {
      e.preventDefault();
      const errorEl = overlay.querySelector('#nt-error');
      const name = overlay.querySelector('#nt-name').value.trim();
      const description = overlay.querySelector('#nt-desc').value.trim();
      if (!name) { errorEl.textContent = 'Team name is required.'; return; }
      try {
        const wsId = await ensureWorkspace();
        const params = new URLSearchParams({ name, description, workspace_id: wsId });
        await Api.post('/admin/teams?' + params.toString());
        UI.toast('Team ' + name + ' created', 'success');
        UI.closeModal();
        loadTeams();
      } catch (err) {
        errorEl.textContent = err.message || 'Could not create team.';
      }
    });
  }

  document.getElementById('new-team-btn').addEventListener('click', openNewTeamModal);
</script>"""

    ready = "loadTeams();"

    html = (
        "<!DOCTYPE html>\n<html lang=\"en\">\n<head>\n<meta charset=\"UTF-8\">\n"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">\n"
        "<title>Teams — Vela Admin</title>\n" + _ASSETS + "\n</head>\n<body>\n"
        + body
        + "\n" + _SCRIPTS + "\n" + script
        + _boot_script("/admin/teams-page", "Teams", ready)
        + "\n</body>\n</html>"
    )
    return html


# =========================================================================
# Tickets — /admin/tickets-page
# =========================================================================

@router.get("/admin/tickets-page", response_class=HTMLResponse)
def admin_tickets_page():
    body = """
<div id="page-content" hidden>
  <div class="page-max">
    <div class="card-header">
      <h1 style="font-size:var(--text-lg)">Tickets</h1>
    </div>
    <div class="tabs" id="status-tabs" role="tablist">
      <button class="tab" data-status="" role="tab" aria-selected="true">All</button>
      <button class="tab" data-status="open" role="tab" aria-selected="false">Open</button>
      <button class="tab" data-status="investigating" role="tab" aria-selected="false">Investigating</button>
      <button class="tab" data-status="resolved" role="tab" aria-selected="false">Resolved</button>
      <button class="tab" data-status="closed" role="tab" aria-selected="false">Closed</button>
    </div>
    <div class="table-wrap" style="margin-top:var(--space-3)">
      <table class="table">
        <thead>
          <tr><th>Title</th><th>Type</th><th>Severity</th><th>Status</th><th>Model</th><th>Team</th><th>Filed by</th><th>Filed</th><th></th></tr>
        </thead>
        <tbody id="tickets-body">""" + "" + """</tbody>
      </table>
    </div>
  </div>
</div>
<div class="auth-loading" id="loading-root">Loading…</div>
"""

    script = """
<script>
  let allTickets = [];
  let activeStatus = '';

  async function loadTickets() {
    const body = document.getElementById('tickets-body');
    body.innerHTML = UI.skeletonRows(9, 5);
    try {
      allTickets = await Api.get('/admin/tickets');
      renderTickets();
    } catch (e) {
      body.innerHTML = '<tr><td colspan="9">' + UI.errorState(e.message, loadTickets) + '</td></tr>';
    }
  }

  function renderTickets() {
    const body = document.getElementById('tickets-body');
    const rows = activeStatus ? allTickets.filter(t => t.status === activeStatus) : allTickets;
    if (!rows.length) {
      body.innerHTML = '<tr><td colspan="9">' + UI.emptyState('No tickets here', 'Nothing matches this filter yet.') + '</td></tr>';
      return;
    }
    body.innerHTML = rows.map(t =>
      '<tr class="is-interactive" data-open-ticket="' + t.id + '">' +
      '<td style="max-width:260px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">' + UI.escapeHtml(t.title) + '</td>' +
      '<td>' + UI.badge(t.ticket_type, 'neutral') + '</td>' +
      '<td>' + UI.severityBadge(t.severity) + '</td>' +
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
        <div style="margin-bottom:.75rem">${UI.severityBadge(t.severity)} ${UI.statusBadge(t.status)} ${UI.badge(t.ticket_type, 'neutral')}</div>
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
      const status = overlay.querySelector('#tk-status').value;
      const resolution_note = overlay.querySelector('#tk-note').value;
      try {
        await Api.patch('/admin/tickets/' + t.id, { status, resolution_note });
        UI.toast('Ticket updated', 'success');
        UI.closeModal();
        loadTickets();
      } catch (err) {
        overlay.querySelector('#tk-error').textContent = err.message || 'Could not update ticket.';
      }
    });
  }

  document.querySelectorAll('#status-tabs .tab').forEach(tab => {
    tab.addEventListener('click', () => {
      document.querySelectorAll('#status-tabs .tab').forEach(t => t.setAttribute('aria-selected', 'false'));
      tab.setAttribute('aria-selected', 'true');
      activeStatus = tab.dataset.status;
      renderTickets();
    });
  });
</script>"""

    ready = "loadTickets();"

    html = (
        "<!DOCTYPE html>\n<html lang=\"en\">\n<head>\n<meta charset=\"UTF-8\">\n"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">\n"
        "<title>Tickets — Vela Admin</title>\n" + _ASSETS + "\n</head>\n<body>\n"
        + body
        + "\n" + _SCRIPTS + "\n" + script
        + _boot_script("/admin/tickets-page", "Tickets", ready)
        + "\n</body>\n</html>"
    )
    return html


# =========================================================================
# Monitoring — /admin/monitoring
# =========================================================================

@router.get("/admin/monitoring", response_class=HTMLResponse)
def admin_monitoring_page():
    ready = "Monitoring.start({role: 'admin'});"

    html = (
        "<!DOCTYPE html>\n<html lang=\"en\">\n<head>\n<meta charset=\"UTF-8\">\n"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">\n"
        "<title>Model Health — Vela Admin</title>\n" + _ASSETS + "\n" + CHART_JS_CDN + "\n" + MONITORING_CSS + "\n</head>\n<body>\n"
        + MONITORING_BODY
        + "\n" + _SCRIPTS + "\n" + MONITORING_SCRIPTS_EXTRA
        + _boot_script("/admin/monitoring", "Model Health", ready)
        + "\n</body>\n</html>"
    )
    return html


# =========================================================================
# Drift — /admin/drift
# =========================================================================

@router.get("/admin/drift", response_class=HTMLResponse)
def admin_drift_page():
    ready = "Drift.start({role: 'admin', actionHrefFor: (e) => '/admin/tickets-page', actionLabel: 'View open tickets'});"

    html = (
        "<!DOCTYPE html>\n<html lang=\"en\">\n<head>\n<meta charset=\"UTF-8\">\n"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">\n"
        "<title>Drift — Vela Admin</title>\n" + _ASSETS + "\n" + CHART_JS_CDN + "\n" + MONITORING_CSS + "\n</head>\n<body>\n"
        + DRIFT_BODY
        + "\n" + _SCRIPTS + "\n" + DRIFT_SCRIPTS_EXTRA
        + _boot_script("/admin/drift", "Drift", ready)
        + "\n</body>\n</html>"
    )
    return html


# =========================================================================
# Remediation — /admin/remediation (spec §15 "Automated remediation")
#
# The four backing endpoints (/api/v1/remediations, /api/v1/remediations/
# {workspace_id}, /api/v1/remediation-logs/{workspace_id}, /api/v1/
# remediations/{id}/test) now accept the admin's own JWT as an
# alternative to a workspace X-API-Key (see _resolve_remediation_actor in
# main.py) — same as every other admin page, this one goes through the
# shared Api helper and needs no separate connection step. An admin JWT
# isn't scoped to one workspace, so configs/logs are loaded across every
# workspace that has at least one deployment (via GET /admin/deployment-
# registry), not just one the admin manually picked.
#
# "Webhooks" and "Retraining" aren't separate resources — they're just
# action_type values on the same RemediationConfig — so there's one page
# here, not three; the sidebar was consolidated to match.
# =========================================================================

@router.get("/admin/automation")
def admin_automation_redirect():
    return RedirectResponse(url="/admin/remediation", status_code=302)


@router.get("/admin/remediation", response_class=HTMLResponse)
def admin_remediation_page():
    body = """
<div id="page-content" hidden>
  <div class="page-max">
    <h1 style="font-size:var(--text-lg);margin-bottom:2px">Remediation</h1>
    <p class="text-secondary" style="font-size:var(--text-sm);margin-bottom:var(--space-5)">
      Configure automatic actions when model drift exceeds a threshold. When triggered, Vela can open a GitHub issue, call a webhook, or start a retraining workflow.
    </p>

    <div id="remediation-content" class="grid-split">
      <div>
        <div class="section-label" style="margin-top:0">New config</div>
        <form id="new-config-form" novalidate>
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
          <button class="btn btn-primary" type="submit" id="nc-submit">Create config</button>
        </form>
      </div>

      <div>
        <div class="section-label" style="margin-top:0">Configured rules</div>
        <div class="table-wrap" style="margin-bottom:var(--space-5)">
          <table class="table">
            <thead><tr><th>Deployment</th><th>Threshold</th><th>Action</th><th>Target</th><th>Status</th><th>Last triggered</th><th></th></tr></thead>
            <tbody id="configs-body"></tbody>
          </table>
        </div>

        <div class="section-label">Remediation logs</div>
        <div class="table-wrap">
          <table class="table">
            <thead><tr><th>Deployment</th><th>Drift score</th><th>Action</th><th>Status</th><th>Triggered</th></tr></thead>
            <tbody id="logs-body"></tbody>
          </table>
        </div>
      </div>
    </div>
  </div>
</div>
<div class="auth-loading" id="loading-root">Loading&hellip;</div>
"""

    script = """
<script>
  // Registry rows this admin has already loaded — used to resolve a
  // config/log's deployment_id to a real name instead of just "#N", and
  // to populate the New config modal's deployment picker. Also, since an
  // admin JWT isn't scoped to one workspace the way an API key is, this
  // is what determines *which* workspaces to ask /api/v1/remediations/
  // {workspace_id} and /api/v1/remediation-logs/{workspace_id} about —
  // every workspace with at least one deployment, unioned together.
  let registryDeployments = [];

  function deploymentLabel(id) {
    const d = registryDeployments.find(r => r.id === id);
    return d ? d.name : ('Deployment #' + id);
  }

  async function loadAll() {
    const body = document.getElementById('configs-body');
    body.innerHTML = UI.skeletonRows(3, 7);
    try {
      registryDeployments = await Api.get('/admin/deployment-registry');
      renderDeploymentPicker();
      const workspaceIds = Array.from(new Set(registryDeployments.map(d => d.workspace_id).filter(id => id != null)));

      const [configResults, logResults] = await Promise.all([
        Promise.allSettled(workspaceIds.map(ws => Api.get('/api/v1/remediations/' + ws))),
        Promise.allSettled(workspaceIds.map(ws => Api.get('/api/v1/remediation-logs/' + ws))),
      ]);
      const configs = configResults.filter(r => r.status === 'fulfilled').flatMap(r => r.value);
      const logs = logResults.filter(r => r.status === 'fulfilled').flatMap(r => r.value);

      renderConfigs(configs);
      renderLogs(logs);
    } catch (e) {
      body.innerHTML = '<tr><td colspan="7">' + UI.errorState(e.message, loadAll) + '</td></tr>';
    }
  }

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

  function renderConfigs(configs) {
    const body = document.getElementById('configs-body');
    if (!configs.length) {
      body.innerHTML = '<tr><td colspan="7">' + UI.emptyState('No remediation configs yet', 'Create one to automatically react when drift crosses a threshold.') + '</td></tr>';
      return;
    }
    body.innerHTML = configs.map(c =>
      '<tr>' +
      '<td class="mono">' + UI.escapeHtml(deploymentLabel(c.deployment_id)) + '</td>' +
      '<td>' + c.drift_threshold + '</td>' +
      '<td><span class="chip-mono">' + UI.escapeHtml(c.action_type) + '</span></td>' +
      '<td class="text-secondary" style="max-width:220px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">' + UI.escapeHtml(c.target || '—') + '</td>' +
      '<td>' + UI.statusBadge(c.is_active ? 'active' : 'inactive') + '</td>' +
      '<td class="text-secondary">' + (c.last_triggered_at ? UI.timeAgo(c.last_triggered_at) : 'never') + '</td>' +
      '<td style="text-align:right"><button class="link-action" data-test="' + c.id + '" type="button">Test</button></td>' +
      '</tr>'
    ).join('');
    body.querySelectorAll('[data-test]').forEach(btn => {
      btn.addEventListener('click', () => testConfig(btn.dataset.test));
    });
  }

  function renderLogs(logs) {
    const body = document.getElementById('logs-body');
    if (!logs.length) {
      body.innerHTML = '<tr><td colspan="5">' + UI.emptyState('No remediation runs yet', 'Triggered actions will be logged here.') + '</td></tr>';
      return;
    }
    body.innerHTML = logs.map(l =>
      '<tr>' +
      '<td class="mono">' + UI.escapeHtml(deploymentLabel(l.deployment_id)) + '</td>' +
      '<td>' + Number(l.drift_score).toFixed(3) + '</td>' +
      '<td><span class="chip-mono">' + UI.escapeHtml(l.action_type) + '</span></td>' +
      '<td>' + UI.statusBadge(l.status) + '</td>' +
      '<td class="text-secondary">' + UI.timeAgo(l.triggered_at) + '</td>' +
      '</tr>'
    ).join('');
  }

  async function testConfig(id) {
    try {
      const result = await Api.post('/api/v1/remediations/' + id + '/test', {});
      const ok = result.status === 'success';
      UI.toast('Test ' + (ok ? 'succeeded' : 'failed') + ': ' + (result.response || result.status), ok ? 'success' : 'danger', 6000);
      loadAll();
    } catch (e) {
      UI.toast('Test failed: ' + e.message, 'danger');
    }
  }

  function targetHintFor(actionType) {
    if (actionType === 'github_issue') return 'GitHub repo as "owner/repo" — optional, falls back to the server-configured repo if left blank.';
    if (actionType === 'webhook') return 'Webhook URL to POST a JSON payload to — required.';
    if (actionType === 'retrain') return 'GitHub Actions workflow filename to dispatch — optional, defaults to retrain.yml.';
    return '';
  }

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
    try {
      await Api.post('/api/v1/remediations', { deployment_id, drift_threshold, action_type, target });
      UI.toast('Remediation config created', 'success');
      document.getElementById('new-config-form').reset();
      loadAll();
    } catch (err) {
      errorEl.textContent = err.message || 'Could not create config.';
    } finally {
      submitBtn.disabled = false;
    }
  });
</script>"""

    ready = "loadAll();"

    html = (
        "<!DOCTYPE html>\n<html lang=\"en\">\n<head>\n<meta charset=\"UTF-8\">\n"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">\n"
        "<title>Remediation — Vela Admin</title>\n" + _ASSETS + "\n</head>\n<body>\n"
        + body
        + "\n" + _SCRIPTS + "\n" + script
        + _boot_script("/admin/remediation", "Remediation", ready)
        + "\n</body>\n</html>"
    )
    return html


# =========================================================================
# Documentation — /admin/docs
# =========================================================================

@router.get("/admin/docs", response_class=HTMLResponse)
def admin_docs_page():
    ready = "Docs.start({role: 'admin'});"

    html = (
        "<!DOCTYPE html>\n<html lang=\"en\">\n<head>\n<meta charset=\"UTF-8\">\n"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">\n"
        "<title>Documentation — Vela Admin</title>\n" + _ASSETS + "\n</head>\n<body>\n"
        + DOCS_BODY
        + "\n" + _SCRIPTS + "\n" + DOCS_SCRIPTS_EXTRA
        + _boot_script("/admin/docs", "Documentation", ready)
        + "\n</body>\n</html>"
    )
    return html


# =========================================================================
# Settings — /admin/settings
# =========================================================================

@router.get("/admin/settings", response_class=HTMLResponse)
def admin_settings_page():
    ready = "Settings.start(user);"

    html = (
        "<!DOCTYPE html>\n<html lang=\"en\">\n<head>\n<meta charset=\"UTF-8\">\n"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">\n"
        "<title>Settings — Vela Admin</title>\n" + _ASSETS + "\n</head>\n<body>\n"
        + SETTINGS_BODY
        + "\n" + _SCRIPTS + "\n" + SETTINGS_SCRIPTS_EXTRA
        + _boot_script("/admin/settings", "Settings", ready)
        + "\n</body>\n</html>"
    )
    return html


# =========================================================================
# Model Registry — /admin/models
#
# GET /admin/deployment-registry (every Deployment row) decides which
# rows exist; GET /models/status is merged in by id to attach each row's
# live health-check status, since the registry's own Deployment.status
# is only set once at deploy/upload time and doesn't track a running
# pod's actual reachability. No other source feeds this page — the two
# hardcoded core services (DistilBERT Sentiment / distilbart-mnli
# Zero-Shot) this used to also show, from before either was a real
# Deployment row, are gone.
# =========================================================================

@router.get("/admin/models", response_class=HTMLResponse)
def admin_models_page():
    body = """
<div id="page-content" hidden>
  <div class="page-max">
    <h1 style="font-size:var(--text-lg);margin-bottom:2px">Model Registry</h1>
    <p class="text-secondary" style="font-size:var(--text-sm);margin-bottom:var(--space-5)">
      Every model deployed on the platform.
    </p>
    <div class="table-wrap">
      <table class="table">
        <thead><tr><th>Model</th><th>Task</th><th>Source</th><th>Status</th><th></th></tr></thead>
        <tbody id="registry-body"></tbody>
      </table>
    </div>
  </div>
</div>
<div class="auth-loading" id="loading-root">Loading&hellip;</div>
"""

    script = """
<script>
  // Every row comes from the registry (the real DB Deployment, and the
  // source of truth for id/model_type/is_active — what management
  // actions below need); /models/status is merged in by id purely for
  // live health-check status, since Deployment.status is only ever set
  // once at deploy/upload time.
  let registryRows = [];
  let managementApiKey = '';

  async function loadRegistry() {
    const body = document.getElementById('registry-body');
    body.innerHTML = UI.skeletonRows(5, 5);
    try {
      const [registry, live] = await Promise.all([
        Api.get('/admin/deployment-registry'), Api.get('/models/status')
      ]);
      const liveById = new Map(live.map(m => [m.id, m]));

      const rows = registry.map(reg => {
        const l = liveById.get(reg.id);
        return { name: reg.name, task: reg.task_type, status: l ? l.status : reg.status, reg };
      });
      registryRows = rows;

      if (!rows.length) {
        body.innerHTML = '<tr><td colspan="5">' + UI.emptyState('No models registered yet', 'Deploy a model from the Deployments page to see it here.') + '</td></tr>';
        return;
      }
      body.innerHTML = rows.map(renderRegistryRow).join('');
      wireRegistryRows();
    } catch (e) {
      body.innerHTML = '<tr><td colspan="5">' + UI.errorState(e.message, loadRegistry) + '</td></tr>';
    }
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
      '<td style="text-align:right;display:flex;gap:var(--space-3);align-items:center;justify-content:flex-end;flex-wrap:wrap">' + actions.join('') + '</td>' +
      '</tr>';
  }

  // Only custom models get the inline pencil — task_type on a
  // HuggingFace deployment mirrors deploy-model.yml's own "task" input
  // and editing it here wouldn't change anything about the running
  // deployment, just make the label lie about what dispatched it.
  function taskCellHtml(row, idx) {
    const isCustom = (row.reg ? row.reg.model_type : 'huggingface') === 'custom';
    if (!isCustom) return '<span class="chip-mono">' + UI.escapeHtml(row.task) + '</span>';
    return '<span class="chip-mono">' + UI.escapeHtml(row.task) + '</span>' +
      '<button class="link-action" data-edit-task="' + idx + '" type="button" style="margin-left:.4rem" title="Edit task type" aria-label="Edit task type">Edit</button>';
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
      '<input class="input" id="task-edit-' + idx + '" style="font-size:var(--text-sm);padding:2px 6px;width:11rem;display:inline-block" value="' + UI.escapeHtml(row.task) + '">' +
      '<button class="btn btn-primary btn-sm" id="task-save-' + idx + '" type="button" style="margin-left:.3rem">Save</button>' +
      '<button class="btn btn-ghost btn-sm" id="task-cancel-' + idx + '" type="button">Cancel</button>';

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
  // uses) — prompted for once, lazily, and cached for the rest of the
  // page's lifetime rather than shown as a permanent field.
  function ensureApiKey() {
    if (managementApiKey) return Promise.resolve(managementApiKey);
    return new Promise((resolve) => {
      const overlay = UI.openModal({
        title: 'API key required',
        bodyHtml: `
          <p class="text-secondary" style="font-size:var(--text-sm);margin-bottom:.75rem">An unscoped workspace API key is needed to manage models — see API Keys.</p>
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
  // inside its button handler — UI.openModal() closes whatever modal is
  // currently open before showing a new one, so nesting them here would
  // close the confirm dialog out from under itself.
  async function confirmDeleteModel(row) {
    if (!row.reg) return;
    const key = await ensureApiKey();
    if (!key) return;

    const overlay = UI.openModal({
      title: 'Delete ' + row.name,
      bodyHtml: `
        <div class="alert alert-danger" style="margin-bottom:.75rem">
          <div><div class="alert-title">This cannot be undone</div><div class="alert-body">This will remove the model and revoke all team access. Type the model name to confirm.</div></div>
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

    ready = "loadRegistry();"

    html = (
        "<!DOCTYPE html>\n<html lang=\"en\">\n<head>\n<meta charset=\"UTF-8\">\n"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">\n"
        "<title>Model Registry — Vela Admin</title>\n" + _ASSETS + "\n</head>\n<body>\n"
        + body
        + "\n" + _SCRIPTS + "\n" + script
        + _boot_script("/admin/models", "Model Registry", ready)
        + "\n</body>\n</html>"
    )
    return html


# =========================================================================
# Deployment Manager — /admin/deployments
# =========================================================================

@router.get("/admin/deployments", response_class=HTMLResponse)
def admin_deployments_page():
    body = """
<div id="page-content" hidden>
  <div class="page-max">
    <h1 style="font-size:var(--text-lg);margin-bottom:2px">Deployments</h1>
    <p class="text-secondary" style="font-size:var(--text-sm);margin-bottom:var(--space-5)">
      Operational status of every deployment, and a form to trigger a new one.
    </p>

    <div class="grid-split">
    <div>
    <div class="section-label" style="margin-top:0">Deploy a model</div>
    <div class="card">
      <form id="deploy-form" novalidate>
        <div class="field"><label class="field-label" for="dp-model">HuggingFace model name</label><input class="input" id="dp-model" placeholder="e.g. distilbert-base-uncased-finetuned-sst-2-english" required></div>
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
        <div id="dp-success" style="display:none;margin-bottom:1rem"></div>
        <button class="btn btn-primary" type="submit" id="dp-submit">Deploy via GitHub Actions</button>
      </form>
    </div>

    <div class="section-label">Deploy a custom model</div>
    <p class="text-secondary" style="font-size:var(--text-sm);margin-bottom:var(--space-3)">Upload your own trained model with a prediction script</p>
    <div class="card">
      <a class="link-secondary" style="font-size:var(--text-xs);display:inline-block;margin-bottom:1rem" href="/api/v1/custom-model-template" download>Download template &rarr;</a>
      <form id="custom-deploy-form" novalidate>
        <div class="field">
          <label class="field-label" for="cm-name">Deployment name</label>
          <input class="input" id="cm-name" placeholder="lowercase-with-hyphens" required>
          <div class="field-hint">Lowercase letters, numbers, and hyphens only.</div>
        </div>
        <div class="field">
          <label class="field-label" for="cm-task-type">Task type <span class="text-muted">(optional)</span></label>
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
        <div class="field" id="cm-schema-field" style="display:none">
          <label class="field-label" for="cm-input-schema">Input schema</label>
          <textarea class="textarea" id="cm-input-schema" placeholder='{"age": "number", "income": "number", "risk_score": "number"}'></textarea>
          <div class="field-hint">Describes the JSON fields callers should send &mdash; shown to them, not enforced.</div>
        </div>
        <div class="field">
          <label class="field-label" for="cm-predict-file">predict.py</label>
          <input class="input" type="file" id="cm-predict-file" accept=".py" required>
        </div>
        <div class="field">
          <label class="field-label" for="cm-model-files">Model files</label>
          <input class="input" type="file" id="cm-model-files" accept=".pkl,.joblib,.pt,.bin,.onnx,.h5,.safetensors" multiple required>
        </div>
        <div class="field">
          <label class="field-label" for="cm-requirements-file">requirements.txt <span class="text-muted">(optional)</span></label>
          <input class="input" type="file" id="cm-requirements-file" accept=".txt">
          <div class="field-hint">List any Python packages your predict.py needs beyond scikit-learn, joblib, pandas, numpy.</div>
        </div>
        <div class="field-error" id="cm-error" role="alert"></div>
        <div id="cm-success" style="display:none;margin-bottom:1rem"></div>
        <button class="btn btn-primary" type="submit" id="cm-submit">Upload and deploy</button>
      </form>
    </div>
    </div>

    <div>
    <div class="section-label" style="margin-top:0">Live deployments</div>
    <div class="table-wrap">
      <table class="table">
        <thead><tr><th>Deployment</th><th>Model</th><th>Task</th><th>Status</th><th>Replicas</th><th>Managed by</th></tr></thead>
        <tbody id="deployments-body"></tbody>
      </table>
    </div>
    </div>
    </div>
  </div>
</div>
<div class="auth-loading" id="loading-root">Loading&hellip;</div>
"""

    script = """
<script>
  async function loadDeployments() {
    const body = document.getElementById('deployments-body');
    body.innerHTML = UI.skeletonRows(6, 3);
    try {
      const [deployments, registry] = await Promise.all([
        Api.get('/deployments'), Api.get('/admin/deployment-registry')
      ]);
      const registryByName = new Map(registry.map(r => [r.name, r]));

      // GET /deployments reads model/task straight off the k8s Deployment
      // (MODEL_NAME/TASK_TYPE env vars) — custom-runner pods only ever set
      // INPUT_TYPE/INPUT_SCHEMA, so both come back "unknown" for every
      // custom model there. The registry (DB Deployment row) has the real
      // values, so it wins whenever a match exists — same fix as the
      // task_type column on /admin/models, for the same underlying reason.
      // It also carries model_type, which "Managed by" shows instead of
      // the old always-"platform"/hardcoded-"core service" label.
      const rows = deployments.map(d => {
        const reg = registryByName.get(d.name) || null;
        return {
          name: d.name, model: (reg && reg.model_name) || d.model_name, task: (reg && reg.task_type) || d.task_type,
          status: d.status, replicas: d.ready + '/' + d.desired, model_type: reg ? reg.model_type : 'huggingface',
        };
      });
      if (!rows.length) {
        body.innerHTML = '<tr><td colspan="6">' + UI.emptyState('No deployments yet', 'Use the form below to deploy your first model.') + '</td></tr>';
        return;
      }
      body.innerHTML = rows.map(r =>
        '<tr><td class="mono">' + UI.escapeHtml(r.name) + '</td><td class="text-secondary">' + UI.escapeHtml(r.model || '—') + '</td><td><span class="chip-mono">' + UI.escapeHtml(r.task) + '</span></td>' +
        '<td>' + UI.statusBadge(r.status) + '</td><td class="text-secondary">' + r.replicas + '</td><td class="text-secondary">' + UI.escapeHtml(r.model_type) + '</td></tr>'
      ).join('');
    } catch (e) {
      body.innerHTML = '<tr><td colspan="6">' + UI.errorState(e.message, loadDeployments) + '</td></tr>';
    }
  }

  document.getElementById('deploy-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    const errorEl = document.getElementById('dp-error');
    const successEl = document.getElementById('dp-success');
    const submitBtn = document.getElementById('dp-submit');
    errorEl.textContent = '';
    successEl.style.display = 'none';
    const model_name = document.getElementById('dp-model').value.trim();
    const task_type = document.getElementById('dp-task').value;
    const deployment_name = document.getElementById('dp-name').value.trim();
    if (!model_name || !deployment_name) { errorEl.textContent = 'Fill in all fields.'; return; }
    if (!/^[a-z0-9-]+$/.test(deployment_name)) { errorEl.textContent = 'Deployment name: lowercase letters, numbers, hyphens only.'; return; }
    submitBtn.disabled = true;
    submitBtn.textContent = 'Triggering…';
    try {
      const result = await Api.post('/deploy-model', { model_name, task_type, deployment_name });
      successEl.style.display = 'block';
      successEl.innerHTML = UI.badge('Triggered', 'success', true) +
        ' <span class="text-secondary" style="font-size:var(--text-sm)">&ldquo;' + UI.escapeHtml(deployment_name) + '&rdquo; will appear here in ~5&ndash;10 min.' +
        (result.deployment_id ? ' <a class="link-secondary" href="/admin/docs?deployment_id=' + result.deployment_id + '">Document it now &rarr;</a>' : '') +
        '</span>';
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
    document.getElementById('cm-schema-field').style.display = e.target.value === 'json' ? 'block' : 'none';
  });

  document.getElementById('custom-deploy-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    const errorEl = document.getElementById('cm-error');
    const successEl = document.getElementById('cm-success');
    const submitBtn = document.getElementById('cm-submit');
    errorEl.textContent = '';
    successEl.style.display = 'none';

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
    // request/response — there's no real "upload finished, now
    // triggering" boundary to observe. This timer approximates it so the
    // button doesn't just sit on "Uploading files…" for however long the
    // whole thing takes.
    const stageTimer = setTimeout(() => { submitBtn.textContent = 'Triggering deployment…'; }, 1200);

    try {
      const workspaces = await Api.get('/workspaces');
      if (!workspaces.length) throw new Error('No workspace found — create a team first.');

      const form = new FormData();
      form.append('deployment_name', deployment_name);
      form.append('input_type', input_type);
      form.append('workspace_id', workspaces[0].id);
      if (task_type) form.append('task_type', task_type);
      if (input_type === 'json' && input_schema) form.append('input_schema', input_schema);
      form.append('predict_file', predictFile);
      Array.from(modelFiles).forEach(f => form.append('model_files', f));
      if (requirementsFile) form.append('requirements_file', requirementsFile);

      // Uses the logged-in admin's JWT session (Authorization: Bearer) —
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
      successEl.style.display = 'block';
      successEl.innerHTML = UI.badge('Queued', 'success', true) +
        ' <span class="text-secondary" style="font-size:var(--text-sm)">Deployment #' + data.deployment_id + ' queued&hellip;</span>';
      UI.toast('Custom model deployment triggered', 'success');
      document.getElementById('custom-deploy-form').reset();
      document.getElementById('cm-schema-field').style.display = 'none';
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
  // timer — no session/queue state to lose on a page reload.
  function customStatusLabel(phase) {
    return {
      downloading: 'Downloading model files…',
      provisioning: 'Starting…',
      running: 'Running',
      failed: 'Failed',
      unknown: 'Unknown',
    }[phase] || phase;
  }

  function customStatusVariant(phase) {
    if (phase === 'running') return 'success';
    if (phase === 'failed') return 'danger';
    return 'warning';
  }

  function pollCustomModelStatus(deploymentId, statusEl) {
    const maxAttempts = 60; // ~5 minutes at 5s intervals — then just stop; the table above still reflects whatever the last known status was.
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
        statusEl.innerHTML = UI.badge(customStatusLabel(phase), customStatusVariant(phase), true) +
          ' <span class="text-secondary" style="font-size:var(--text-sm)">Deployment #' + deploymentId +
          (phase === 'running' ? ' is running.' : phase === 'failed' ? ' failed to deploy.' + detail : ' is being provisioned&hellip;') +
          '</span>';
        if (phase === 'running' || phase === 'failed') {
          loadDeployments();
          return;
        }
      } catch (e) {
        // Network hiccup mid-poll — keep trying rather than giving up on one blip.
      }
      if (attempts < maxAttempts) setTimeout(tick, 5000);
    }

    tick();
  }
</script>"""

    ready = "loadDeployments();"

    html = (
        "<!DOCTYPE html>\n<html lang=\"en\">\n<head>\n<meta charset=\"UTF-8\">\n"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">\n"
        "<title>Deployments — Vela Admin</title>\n" + _ASSETS + "\n</head>\n<body>\n"
        + body
        + "\n" + _SCRIPTS + "\n" + script
        + _boot_script("/admin/deployments", "Deployments", ready)
        + "\n</body>\n</html>"
    )
    return html


# =========================================================================
# Infrastructure — /admin/infrastructure
#
# "Running instances" and the services table are built from
# /models/status + /deployments' replica counts, not the Kubernetes Pod
# API directly (no endpoint exposes individual Pod objects) — labeled
# accordingly rather than claiming pod-level precision. "Uptime" is
# derived from the most recent "deploy" event on /timeline (itself
# sourced from Prometheus process_start_time_seconds), with a graceful
# fallback since /timeline 500s if Prometheus is unreachable.
# =========================================================================

@router.get("/admin/infrastructure", response_class=HTMLResponse)
def admin_infrastructure_page():
    body = """
<div id="page-content" hidden>
  <div class="page-max">
    <h1 style="font-size:var(--text-lg);margin-bottom:2px">Infrastructure</h1>
    <p class="text-secondary" style="font-size:var(--text-sm);margin-bottom:var(--space-5)">Node resource usage and running services.</p>

    <div class="grid-2" style="margin-bottom:var(--space-4)">
      <div class="card">
        <div class="meter-label"><span>Node CPU usage</span><span id="cpu-val">&mdash;</span></div>
        <div class="meter-track"><div class="meter-fill" id="cpu-fill" style="width:0%"></div></div>
      </div>
      <div class="card">
        <div class="meter-label"><span>Node memory usage</span><span id="mem-val">&mdash;</span></div>
        <div class="meter-track"><div class="meter-fill" id="mem-fill" style="width:0%"></div></div>
      </div>
    </div>

    <div class="metric-row" style="margin-bottom:var(--space-5)">
      <div class="metric-tile"><div class="metric-tile-value" id="pod-count">&mdash;</div><div class="metric-tile-label">Running instances</div></div>
      <div class="metric-tile"><div class="metric-tile-value" id="uptime-val" style="font-size:var(--text-md)">&mdash;</div><div class="metric-tile-label">Uptime since last deploy</div></div>
    </div>

    <div class="section-label">Services</div>
    <div class="table-wrap">
      <table class="table">
        <thead><tr><th>Name</th><th>Type</th><th>Status</th><th>Replicas</th></tr></thead>
        <tbody id="services-body"></tbody>
      </table>
    </div>
  </div>
</div>
<div class="auth-loading" id="loading-root">Loading&hellip;</div>
"""

    script = """
<script>
  function setMeter(prefix, pct, label) {
    const fill = document.getElementById(prefix + '-fill');
    const val = document.getElementById(prefix + '-val');
    if (fill) {
      fill.style.width = Math.min(100, Math.max(0, pct)) + '%';
      fill.className = 'meter-fill' + (pct > 85 ? ' is-danger' : pct > 65 ? ' is-warning' : '');
    }
    if (val) val.textContent = label;
  }

  function fmtN(n, dec) { return (n == null || isNaN(n)) ? '—' : Number(n).toFixed(dec); }

  async function loadMetrics() {
    try {
      const d = await Api.get('/metrics-summary');
      const cpu = Math.round(d.node_cpu_percent || 0);
      const mu = d.node_memory_used_gb || 0;
      const mt = d.node_memory_total_gb || 0;
      const mp = mt > 0 ? Math.round((mu / mt) * 100) : 0;
      setMeter('cpu', cpu, cpu + '%');
      setMeter('mem', mp, fmtN(mu, 1) + 'GB / ' + fmtN(mt, 1) + 'GB (' + mp + '%)');
    } catch (e) {
      UI.toast('Could not load node metrics: ' + e.message, 'danger');
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
      el.textContent = 'Unavailable';
    }
  }
</script>"""

    ready = "loadMetrics(); loadServices(); loadUptime();"

    html = (
        "<!DOCTYPE html>\n<html lang=\"en\">\n<head>\n<meta charset=\"UTF-8\">\n"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">\n"
        "<title>Infrastructure — Vela Admin</title>\n" + _ASSETS + "\n</head>\n<body>\n"
        + body
        + "\n" + _SCRIPTS + "\n" + script
        + _boot_script("/admin/infrastructure", "Infrastructure", ready)
        + "\n</body>\n</html>"
    )
    return html


# =========================================================================
# API Keys — /admin/api-keys
#
# GET /workspaces returns only workspaces the CALLING user belongs to —
# there is no platform-wide "list every workspace" endpoint, and
# is_admin doesn't grant broader visibility there. This shows the
# admin's own workspace memberships (typically ones bootstrapped from
# the Teams page), not necessarily every workspace on the platform.
# =========================================================================

@router.get("/admin/api-keys", response_class=HTMLResponse)
def admin_api_keys_page():
    body = """
<div id="page-content" hidden>
  <div class="page-max">
    <div class="card-header">
      <div>
        <h1 style="font-size:var(--text-lg);margin-bottom:2px">API Keys</h1>
        <p class="text-secondary" style="font-size:var(--text-sm)">
          Workspaces you belong to and their keys. There's no platform-wide workspace list in the API &mdash;
          this shows workspaces your admin account is a member of.
        </p>
      </div>
      <button class="btn btn-primary btn-sm" id="new-key-btn" type="button">New key</button>
    </div>
    <div class="table-wrap">
      <table class="table">
        <thead><tr><th>Key prefix</th><th>Name</th><th>Scope</th><th>Created</th><th></th></tr></thead>
        <tbody id="keys-body"></tbody>
      </table>
    </div>
  </div>
</div>
<div class="auth-loading" id="loading-root">Loading&hellip;</div>
"""

    script = """
<script>
  let cachedWorkspaces = [];

  async function loadWorkspaces() {
    const body = document.getElementById('keys-body');
    body.innerHTML = UI.skeletonRows(4, 5);
    try {
      cachedWorkspaces = await Api.get('/workspaces');
      if (!cachedWorkspaces.length) {
        body.innerHTML = '<tr><td colspan="5">' + UI.emptyState('No workspaces yet', 'Create a team from the Teams page to bootstrap your first workspace.') + '</td></tr>';
        return;
      }
      const perWorkspace = await Promise.allSettled(cachedWorkspaces.map(ws => Api.get('/workspaces/' + ws.id + '/api-keys')));
      const rows = [];
      perWorkspace.forEach((r, i) => {
        if (r.status !== 'fulfilled') return;
        r.value.forEach(k => rows.push(Object.assign({}, k, { ws_id: cachedWorkspaces[i].id, ws_name: cachedWorkspaces[i].name })));
      });
      renderKeys(rows);
    } catch (e) {
      body.innerHTML = '<tr><td colspan="5">' + UI.errorState(e.message, loadWorkspaces) + '</td></tr>';
    }
  }

  function renderKeys(rows) {
    const body = document.getElementById('keys-body');
    if (!rows.length) {
      body.innerHTML = '<tr><td colspan="5">' + UI.emptyState('No keys yet', 'Generate one with the button above.') + '</td></tr>';
      return;
    }
    body.innerHTML = rows.map(k =>
      '<tr>' +
      '<td class="mono">' + UI.escapeHtml(k.prefix) + '&hellip;</td>' +
      '<td>' + UI.escapeHtml(k.name) + '</td>' +
      '<td class="text-secondary">' + UI.escapeHtml(k.ws_name) + '</td>' +
      '<td class="text-secondary">' + UI.fmtDate(k.created_at) + (k.last_used_at ? ' &middot; used ' + UI.timeAgo(k.last_used_at) : ' &middot; never used') + '</td>' +
      '<td style="text-align:right"><button class="link-action link-danger" data-revoke-key="' + k.ws_id + ':' + k.id + '" data-name="' + UI.escapeHtml(k.name) + '" type="button">Revoke</button></td>' +
      '</tr>'
    ).join('');
    body.querySelectorAll('[data-revoke-key]').forEach(btn => {
      btn.addEventListener('click', () => {
        const parts = btn.dataset.revokeKey.split(':');
        revokeKey(parts[0], parts[1], btn.dataset.name);
      });
    });
  }

  async function revokeKey(wsId, keyId, name) {
    if (!confirm('Revoke "' + name + '"? Anything using this key will stop working immediately.')) return;
    try {
      await Api.del('/workspaces/' + wsId + '/api-keys/' + keyId);
      UI.toast('Key revoked', 'success');
      loadWorkspaces();
    } catch (e) {
      UI.toast(e.message || 'Could not revoke key', 'danger');
    }
  }

  function openNewKeyModal() {
    const wsOptions = cachedWorkspaces.map(ws => '<option value="' + ws.id + '">' + UI.escapeHtml(ws.name) + '</option>').join('');
    const overlay = UI.openModal({
      title: 'New API key',
      bodyHtml: `
        <form id="new-key-form" novalidate>
          ${cachedWorkspaces.length > 1 ? `<div class="field"><label class="field-label" for="nk-ws">Workspace</label><select class="select" id="nk-ws">${wsOptions}</select></div>` : ''}
          <div class="field"><label class="field-label" for="nk-name">Key name</label><input class="input" id="nk-name" placeholder="e.g. production, ci-cd" required></div>
          <div class="field-error" id="nk-error" role="alert"></div>
        </form>`,
      footerHtml: `<button class="btn btn-ghost" id="nk-cancel" type="button">Cancel</button>
                   <button class="btn btn-primary" id="nk-submit" type="submit" form="new-key-form">Generate key</button>`,
    });
    overlay.querySelector('#nk-cancel').addEventListener('click', UI.closeModal);
    overlay.querySelector('#new-key-form').addEventListener('submit', async (e) => {
      e.preventDefault();
      const wsSel = overlay.querySelector('#nk-ws');
      const wsId = wsSel ? wsSel.value : cachedWorkspaces[0].id;
      const errorEl = overlay.querySelector('#nk-error');
      const name = overlay.querySelector('#nk-name').value.trim();
      if (!name) { errorEl.textContent = 'Give the key a name.'; return; }
      try {
        const result = await Api.post('/workspaces/' + wsId + '/api-keys', { name });
        UI.closeModal();
        showRawKey(result);
        loadWorkspaces();
      } catch (err) {
        errorEl.textContent = err.message || 'Could not create key.';
      }
    });
  }

  function showRawKey(result) {
    const overlay = UI.openModal({
      title: 'Copy your API key',
      bodyHtml: `
        <div class="alert alert-warning" style="margin-bottom:.75rem">
          <div><div class="alert-title">Shown once</div><div class="alert-body">This key will not be shown again &mdash; copy it now.</div></div>
        </div>
        <div class="field">
          <label class="field-label">${UI.escapeHtml(result.name)}</label>
          <input class="input" id="raw-key" value="${UI.escapeHtml(result.key)}" readonly style="font-size:var(--text-xs)">
        </div>`,
      footerHtml: `<button class="btn btn-secondary" id="rk-copy" type="button">Copy</button>
                   <button class="btn btn-primary" id="rk-done" type="button">Done</button>`,
    });
    overlay.querySelector('#rk-done').addEventListener('click', UI.closeModal);
    overlay.querySelector('#rk-copy').addEventListener('click', async () => {
      const input = overlay.querySelector('#raw-key');
      const ok = await UI.copyText(input.value);
      if (ok) {
        UI.toast('Copied to clipboard', 'success');
      } else {
        input.select();
        UI.toast('Could not copy automatically — key is selected, press Ctrl/Cmd+C', 'danger');
      }
    });
  }

  document.getElementById('new-key-btn').addEventListener('click', openNewKeyModal);
</script>"""

    ready = "loadWorkspaces();"

    html = (
        "<!DOCTYPE html>\n<html lang=\"en\">\n<head>\n<meta charset=\"UTF-8\">\n"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">\n"
        "<title>API Keys — Vela Admin</title>\n" + _ASSETS + "\n</head>\n<body>\n"
        + body
        + "\n" + _SCRIPTS + "\n" + script
        + _boot_script("/admin/api-keys", "API Keys", ready)
        + "\n</body>\n</html>"
    )
    return html
