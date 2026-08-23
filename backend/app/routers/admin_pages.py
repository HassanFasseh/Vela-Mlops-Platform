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
    CHART_JS_CDN, MONITORING_BODY, MONITORING_SCRIPTS_EXTRA,
    DRIFT_BODY, DRIFT_SCRIPTS_EXTRA,
    DOCS_BODY, DOCS_SCRIPTS_EXTRA,
    SETTINGS_BODY, SETTINGS_SCRIPTS_EXTRA,
)

router = APIRouter()

_ASSETS = """<link rel="stylesheet" href="/static/css/tokens.css">
<link rel="stylesheet" href="/static/css/base.css">
<link rel="stylesheet" href="/static/css/components.css">
<link rel="stylesheet" href="/static/css/shell.css">"""

_SCRIPTS = """<script src="/static/js/api.js"></script>
<script src="/static/js/shell.js"></script>
<script src="/static/js/particles.js"></script>
<script src="/static/js/ui.js"></script>"""

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

    <div class="metric-row" id="metric-row" style="margin:var(--space-5) 0"></div>

    <div class="section-label">Model health</div>
    <div class="table-wrap">
      <table class="table">
        <thead>
          <tr><th>Model</th><th>Task</th><th>Source</th><th>Status</th><th>Detail</th></tr>
        </thead>
        <tbody id="model-health-body">""" + "" + """</tbody>
      </table>
    </div>

    <div class="section-label">Recent tickets</div>
    <div class="card" id="recent-tickets-card"></div>
  </div>
</div>
<div class="auth-loading" id="loading-root">Loading…</div>
"""

    script = """
<script>
  function fmtPct(x) { return (x == null || isNaN(x)) ? '—' : (x * 100).toFixed(1) + '%'; }

  async function loadOverview(user) {
    document.getElementById('greeting').textContent = greetingFor(user);
    const results = await Promise.allSettled([
      Api.get('/admin/users'),
      Api.get('/admin/tickets'),
      Api.get('/models/status'),
      Api.get('/deployments'),
      Api.get('/metrics-summary'),
    ]);
    const [usersR, ticketsR, modelsR, depsR, metricsR] = results;
    const users = usersR.status === 'fulfilled' ? usersR.value : [];
    const tickets = ticketsR.status === 'fulfilled' ? ticketsR.value : [];
    const models = modelsR.status === 'fulfilled' ? modelsR.value : [];
    const deployments = depsR.status === 'fulfilled' ? depsR.value : [];
    const metrics = metricsR.status === 'fulfilled' ? metricsR.value : {};

    renderStatus(models);
    renderMetrics(users, tickets, models, deployments, metrics);
    renderModelHealth(models, deployments);
    renderRecentTickets(tickets);
  }

  function greetingFor(user) {
    const h = new Date().getHours();
    const part = h < 12 ? 'Good morning' : h < 18 ? 'Good afternoon' : 'Good evening';
    return part + ', ' + (user.name || user.username);
  }

  function renderStatus(models) {
    const el = document.getElementById('platform-status');
    if (!models.length) {
      el.innerHTML = UI.badge('Unknown', 'neutral', true) + ' <span class="text-muted">no core services reporting</span>';
      return;
    }
    const offline = models.filter(m => m.status !== 'online').length;
    if (offline === 0) {
      el.innerHTML = UI.badge('Operational', 'success', true);
    } else {
      el.innerHTML = UI.badge('Degraded', 'danger', true) + ' <span class="text-muted">' + offline + ' of ' + models.length + ' core services offline</span>';
    }
  }

  function tile(value, label, variant) {
    return '<div class="metric-tile"><div class="metric-tile-value' + (variant ? ' is-' + variant : '') + '">' + value + '</div><div class="metric-tile-label">' + label + '</div></div>';
  }

  function renderMetrics(users, tickets, models, deployments, metrics) {
    const totalModels = models.length + deployments.length;
    const running = models.filter(m => m.status === 'online').length + deployments.filter(d => d.status === 'running').length;
    const attention = totalModels - running;
    const openTickets = tickets.filter(t => t.status === 'open' || t.status === 'investigating').length;
    const activeUsers = users.filter(u => u.is_active).length;
    document.getElementById('metric-row').innerHTML =
      tile(totalModels, 'Total models') +
      tile(running, 'Running', 'success') +
      tile(attention, 'Needs attention', attention > 0 ? 'warning' : undefined) +
      tile(fmtPct(metrics.drift_score), 'Platform drift') +
      tile(openTickets, 'Open tickets', openTickets > 0 ? 'warning' : undefined) +
      tile(activeUsers, 'Active users');
  }

  function renderModelHealth(models, deployments) {
    const body = document.getElementById('model-health-body');
    const rows = [];
    models.forEach(m => rows.push({
      name: m.name, task: m.task, source: 'Core service',
      status: m.status, detail: 'backing model: ' + (m.model || 'unknown'),
    }));
    deployments.forEach(d => rows.push({
      name: d.name, task: d.task_type, source: 'Deployment',
      status: d.status, detail: d.ready + '/' + d.desired + ' replicas ready',
    }));
    if (!rows.length) {
      body.innerHTML = '<tr><td colspan="5">' + UI.emptyState('No models deployed yet', 'Deployed models and core services will show up here once available.') + '</td></tr>';
      return;
    }
    body.innerHTML = rows.map(r =>
      '<tr><td>' + UI.escapeHtml(r.name) + '</td><td>' + UI.escapeHtml(r.task) + '</td><td>' +
      UI.badge(r.source, 'neutral') + '</td><td>' + UI.statusBadge(r.status) + '</td><td class="text-secondary">' +
      UI.escapeHtml(r.detail) + '</td></tr>'
    ).join('');
  }

  function renderRecentTickets(tickets) {
    const card = document.getElementById('recent-tickets-card');
    if (!tickets.length) {
      card.innerHTML = UI.emptyState('No tickets yet', 'Tickets filed by team members will appear here.');
      return;
    }
    const recent = tickets.slice(0, 5);
    card.innerHTML = recent.map(t =>
      '<div class="row" style="display:flex;justify-content:space-between;align-items:center;gap:.75rem;padding:.5rem 0;border-bottom:1px solid var(--color-border-subtle)">' +
      '<div style="min-width:0">' +
      '<div style="font-size:var(--text-sm);white-space:nowrap;overflow:hidden;text-overflow:ellipsis">' + UI.escapeHtml(t.title) + '</div>' +
      '<div class="text-muted" style="font-size:var(--text-xs)">' + UI.escapeHtml(t.filed_by_name) + ' &middot; ' + UI.timeAgo(t.filed_at) + '</div>' +
      '</div>' +
      '<div style="display:flex;gap:.4rem;flex-shrink:0">' + UI.severityBadge(t.severity) + UI.statusBadge(t.status) + '</div>' +
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
      const action = !u.is_active
        ? '<span class="text-muted" style="font-size:var(--text-xs)">Deactivated</span>'
        : isSelf
          ? '<span class="text-muted" style="font-size:var(--text-xs)">You</span>'
          : '<button class="btn btn-danger btn-sm" data-deactivate="' + u.id + '" data-username="' + UI.escapeHtml(u.username) + '" type="button">Deactivate</button>';
      return '<tr>' +
        '<td>' + UI.escapeHtml(u.username) + '</td>' +
        '<td>' + UI.escapeHtml(u.name) + '</td>' +
        '<td>' + UI.badge(u.is_admin ? 'Admin' : 'Member', u.is_admin ? 'info' : 'neutral') + '</td>' +
        '<td>' + teamBadges + '</td>' +
        '<td>' + UI.statusBadge(u.is_active ? 'active' : 'inactive') + (u.force_password_change ? ' ' + UI.badge('Pending first login', 'warning') : '') + '</td>' +
        '<td class="text-secondary">' + UI.fmtDate(u.created_at) + '</td>' +
        '<td>' + action + '</td>' +
        '</tr>';
    }).join('');

    body.querySelectorAll('[data-deactivate]').forEach(btn => {
      btn.addEventListener('click', () => deactivateUser(btn.dataset.deactivate, btn.dataset.username));
    });
  }

  async function deactivateUser(id, username) {
    if (!confirm('Deactivate ' + username + '? They will no longer be able to log in.')) return;
    try {
      await Api.del('/admin/users/' + id);
      UI.toast(username + ' deactivated', 'success');
      loadUsers();
    } catch (e) {
      UI.toast(e.message || 'Could not deactivate user', 'danger');
    }
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
      const [teams, users] = await Promise.all([Api.get('/admin/teams'), Api.get('/admin/users')]);
      cachedTeams = teams;
      cachedUsers = users;
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
    const memberRows = (t.members || []).length
      ? t.members.map(m =>
          '<div class="row" style="display:flex;justify-content:space-between;align-items:center;padding:.35rem 0">' +
          '<span style="font-size:var(--text-sm)">' + UI.escapeHtml(m.name || m.email || ('User #' + m.user_id)) + ' ' + UI.badge(m.role, m.role === 'lead' ? 'info' : 'neutral') + '</span>' +
          '<button class="btn btn-ghost btn-sm" data-remove-member="' + t.id + ':' + m.user_id + '" type="button">Remove</button>' +
          '</div>'
        ).join('')
      : '<div class="text-muted" style="font-size:var(--text-sm);padding:.35rem 0">No members yet</div>';

    const availableUsers = cachedUsers.filter(u => u.is_active && !memberIds.has(u.id));
    const userOptions = availableUsers.map(u => '<option value="' + u.id + '">' + UI.escapeHtml(u.name) + ' (' + UI.escapeHtml(u.username) + ')</option>').join('');

    const perms = t.permissions || [];
    const permRows = perms.length
      ? perms.map(p =>
          '<div class="text-secondary" style="font-size:var(--text-xs);padding:.25rem 0">' +
          UI.escapeHtml(p.model_name || p.deployment_name || ('Deployment #' + p.deployment_id)) +
          (p.can_predict ? ' &middot; predict' : '') + (p.can_view_metrics ? ' &middot; view metrics' : '') +
          '</div>'
        ).join('')
      : '<div class="text-muted" style="font-size:var(--text-xs)">No model access granted yet</div>';

    return '<div class="card" style="margin-bottom:var(--space-3)" data-team-card="' + t.id + '">' +
      '<div class="card-header"><div><div class="card-title">' + UI.escapeHtml(t.name) + '</div>' +
      (t.description ? '<div class="card-subtitle">' + UI.escapeHtml(t.description) + '</div>' : '') + '</div></div>' +
      '<div class="section-label" style="margin-top:.5rem">Members</div>' +
      memberRows +
      (availableUsers.length ? (
        '<div class="row" style="display:flex;gap:.5rem;margin-top:.5rem;flex-wrap:wrap">' +
        '<select class="select" data-add-user="' + t.id + '" style="flex:2">' + userOptions + '</select>' +
        '<select class="select" data-add-role="' + t.id + '" style="flex:1"><option value="member">Member</option><option value="lead">Lead</option></select>' +
        '<button class="btn btn-secondary btn-sm" data-add-member="' + t.id + '" type="button">Add</button>' +
        '</div>'
      ) : '') +
      '<div class="section-label">Model access</div>' + permRows +
      '</div>';
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
    ready = "Monitoring.start();"

    html = (
        "<!DOCTYPE html>\n<html lang=\"en\">\n<head>\n<meta charset=\"UTF-8\">\n"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">\n"
        "<title>Model Health — Vela Admin</title>\n" + _ASSETS + "\n" + CHART_JS_CDN + "\n</head>\n<body>\n"
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
    ready = "Drift.start({actionHref: '/admin/tickets-page', actionLabel: 'View open tickets'});"

    html = (
        "<!DOCTYPE html>\n<html lang=\"en\">\n<head>\n<meta charset=\"UTF-8\">\n"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">\n"
        "<title>Drift — Vela Admin</title>\n" + _ASSETS + "\n</head>\n<body>\n"
        + DRIFT_BODY
        + "\n" + _SCRIPTS + "\n" + DRIFT_SCRIPTS_EXTRA
        + _boot_script("/admin/drift", "Drift", ready)
        + "\n</body>\n</html>"
    )
    return html


# =========================================================================
# Remediation — /admin/remediation (spec §15 "Automated remediation")
#
# Unlike every other admin page, these three endpoints
# (/api/v1/remediations, /api/v1/remediation-logs/{workspace_id},
# /api/v1/remediations/{id}/test) authenticate with X-API-Key, not the
# admin's JWT — see main.py. This page never touches the shared Api
# helper for them: Api.request() treats any 401 as "session expired,
# clear the JWT and go to /login", which would silently log the admin
# out over a wrong/missing API key. A separate fetch wrapper is used
# instead, and the key is kept in sessionStorage (tab-scoped), not
# localStorage.
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
    <h1 style="font-size:var(--text-lg);margin-bottom:var(--space-3)">Remediation</h1>

    <div class="alert alert-warning" style="margin-bottom:var(--space-4)">
      <div>
        <div class="alert-title">Uses a workspace API key, not your admin login</div>
        <div class="alert-body">
          These endpoints authenticate with a workspace-scoped API key (X-API-Key), separate from your admin session.
          Generate one from a workspace's API Keys page, then connect below with that key and its workspace ID.
          All configured actions currently react to the same platform-wide drift signal &mdash; there isn't yet a per-model detector.
        </div>
      </div>
    </div>

    <div class="card" id="creds-card" style="margin-bottom:var(--space-5)">
      <div class="card-title" style="margin-bottom:.75rem">Connect</div>
      <div class="grid-creds">
        <div class="field" style="margin-bottom:0"><label class="field-label" for="rk-key">API key</label><input class="input" type="password" id="rk-key" placeholder="aodp_..." autocomplete="off"></div>
        <div class="field" style="margin-bottom:0"><label class="field-label" for="rk-ws">Workspace ID</label><input class="input" type="number" id="rk-ws" placeholder="1"></div>
        <button class="btn btn-primary" id="rk-connect" type="button">Connect</button>
      </div>
      <div class="field-error" id="rk-error" role="alert" style="margin-top:.5rem"></div>
      <div id="rk-status" style="margin-top:.5rem"></div>
    </div>

    <div id="remediation-content" hidden>
      <div class="card-header">
        <div class="section-label" style="margin:0">Remediation configs</div>
        <button class="btn btn-secondary btn-sm" id="new-config-btn" type="button">New config</button>
      </div>
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
<div class="auth-loading" id="loading-root">Loading&hellip;</div>
"""

    script = """
<script>
  const RK_KEY_STORE = 'vela_remediation_key';
  const RK_WS_STORE = 'vela_remediation_ws';

  async function remediationFetch(path, opts) {
    opts = opts || {};
    const apiKey = sessionStorage.getItem(RK_KEY_STORE) || '';
    const headers = Object.assign({ 'X-API-Key': apiKey }, opts.headers);
    let body = opts.body;
    if (body && typeof body !== 'string') {
      body = JSON.stringify(body);
      headers['Content-Type'] = 'application/json';
    }
    const res = await fetch(path, Object.assign({}, opts, { headers, body }));
    const text = await res.text();
    let data = null;
    if (text) { try { data = JSON.parse(text); } catch (e) { data = text; } }
    if (!res.ok) {
      const detail = (data && data.detail) || res.statusText || 'Request failed';
      const err = new Error(detail);
      err.status = res.status;
      throw err;
    }
    return data;
  }

  function currentWorkspaceId() {
    return sessionStorage.getItem(RK_WS_STORE);
  }

  async function connect() {
    const key = document.getElementById('rk-key').value.trim();
    const ws = document.getElementById('rk-ws').value.trim();
    const errorEl = document.getElementById('rk-error');
    const statusEl = document.getElementById('rk-status');
    errorEl.textContent = '';
    if (!key || !ws) {
      errorEl.textContent = 'Enter both an API key and a workspace ID.';
      return;
    }
    sessionStorage.setItem(RK_KEY_STORE, key);
    sessionStorage.setItem(RK_WS_STORE, ws);
    statusEl.textContent = 'Connecting…';
    try {
      await loadAll();
      statusEl.innerHTML = UI.badge('Connected to workspace ' + ws, 'success', true) +
        ' <button class="btn btn-ghost btn-sm" id="rk-disconnect" type="button" style="margin-left:.5rem">Disconnect</button>';
      document.getElementById('rk-disconnect').addEventListener('click', disconnect);
      document.getElementById('remediation-content').hidden = false;
    } catch (e) {
      statusEl.textContent = '';
      errorEl.textContent = e.message || 'Could not connect with this key/workspace.';
      document.getElementById('remediation-content').hidden = true;
      sessionStorage.removeItem(RK_KEY_STORE);
      sessionStorage.removeItem(RK_WS_STORE);
    }
  }

  function disconnect() {
    sessionStorage.removeItem(RK_KEY_STORE);
    sessionStorage.removeItem(RK_WS_STORE);
    document.getElementById('rk-key').value = '';
    document.getElementById('rk-status').innerHTML = '';
    document.getElementById('remediation-content').hidden = true;
  }

  async function loadAll() {
    const ws = currentWorkspaceId();
    const [configs, logs] = await Promise.all([
      remediationFetch('/api/v1/remediations/' + ws),
      remediationFetch('/api/v1/remediation-logs/' + ws),
    ]);
    renderConfigs(configs);
    renderLogs(logs);
  }

  let cachedConfigs = [];

  function renderConfigs(configs) {
    cachedConfigs = configs;
    const body = document.getElementById('configs-body');
    if (!configs.length) {
      body.innerHTML = '<tr><td colspan="7">' + UI.emptyState('No remediation configs yet', 'Create one to automatically react when drift crosses a threshold.') + '</td></tr>';
      return;
    }
    body.innerHTML = configs.map(c =>
      '<tr>' +
      '<td>Deployment #' + c.deployment_id + '</td>' +
      '<td>' + c.drift_threshold + '</td>' +
      '<td>' + UI.badge(c.action_type, 'neutral') + '</td>' +
      '<td class="text-secondary" style="max-width:220px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">' + UI.escapeHtml(c.target || '—') + '</td>' +
      '<td>' + UI.statusBadge(c.is_active ? 'active' : 'inactive') + '</td>' +
      '<td class="text-secondary">' + (c.last_triggered_at ? UI.timeAgo(c.last_triggered_at) : 'never') + '</td>' +
      '<td><button class="btn btn-ghost btn-sm" data-test="' + c.id + '" type="button">Test</button></td>' +
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
      '<td>Deployment #' + l.deployment_id + '</td>' +
      '<td>' + Number(l.drift_score).toFixed(3) + '</td>' +
      '<td>' + UI.badge(l.action_type, 'neutral') + '</td>' +
      '<td>' + UI.statusBadge(l.status) + '</td>' +
      '<td class="text-secondary">' + UI.timeAgo(l.triggered_at) + '</td>' +
      '</tr>'
    ).join('');
  }

  async function testConfig(id) {
    try {
      const result = await remediationFetch('/api/v1/remediations/' + id + '/test', { method: 'POST' });
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

  function openNewConfigModal() {
    const overlay = UI.openModal({
      title: 'New remediation config',
      bodyHtml: `
        <form id="new-config-form" novalidate>
          <div class="field">
            <label class="field-label" for="nc-dep">Deployment ID</label>
            <input class="input" type="number" id="nc-dep" required>
            <div class="field-hint">Deployment IDs aren't listed in the admin UI yet — use the ID returned when the model was deployed or uploaded.</div>
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
            <div class="field-hint" id="nc-target-hint">${targetHintFor('github_issue')}</div>
          </div>
          <div class="field-error" id="nc-error" role="alert"></div>
        </form>`,
      footerHtml: `<button class="btn btn-ghost" id="nc-cancel" type="button">Cancel</button>
                   <button class="btn btn-primary" id="nc-submit" type="submit" form="new-config-form">Create config</button>`,
    });
    overlay.querySelector('#nc-cancel').addEventListener('click', UI.closeModal);
    overlay.querySelector('#nc-action').addEventListener('change', (e) => {
      overlay.querySelector('#nc-target-hint').textContent = targetHintFor(e.target.value);
    });
    overlay.querySelector('#new-config-form').addEventListener('submit', async (e) => {
      e.preventDefault();
      const errorEl = overlay.querySelector('#nc-error');
      const deployment_id = parseInt(overlay.querySelector('#nc-dep').value, 10);
      const drift_threshold = parseFloat(overlay.querySelector('#nc-threshold').value);
      const action_type = overlay.querySelector('#nc-action').value;
      const target = overlay.querySelector('#nc-target').value.trim();
      if (!deployment_id) { errorEl.textContent = 'Deployment ID is required.'; return; }
      if (action_type === 'webhook' && !target) { errorEl.textContent = 'Webhook actions require a target URL.'; return; }
      try {
        await remediationFetch('/api/v1/remediations', { method: 'POST', body: { deployment_id, drift_threshold, action_type, target } });
        UI.toast('Remediation config created', 'success');
        UI.closeModal();
        loadAll();
      } catch (err) {
        errorEl.textContent = err.message || 'Could not create config.';
      }
    });
  }

  document.getElementById('rk-connect').addEventListener('click', connect);
  document.getElementById('new-config-btn').addEventListener('click', openNewConfigModal);

  // Resume a connection already established earlier in this tab session.
  (function restore() {
    const key = sessionStorage.getItem(RK_KEY_STORE);
    const ws = sessionStorage.getItem(RK_WS_STORE);
    if (key && ws) {
      document.getElementById('rk-key').value = key;
      document.getElementById('rk-ws').value = ws;
      connect();
    }
  })();
</script>"""

    ready = ""

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
    ready = "Docs.start();"

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
# Every row here comes from either /models/status (the two hardcoded core
# services, both HuggingFace-hosted) or /deployments (k8s Deployments
# labeled managed-by=platform). Only /deploy-model ever creates one of
# those k8s objects — /api/v1/upload-model stores a DB record and never
# touches the Kubernetes API — so "source" is honestly "huggingface" for
# every row this page can show; uploaded models have no way to surface
# here at all. There's also no endpoint mapping a k8s deployment name to
# its DB Deployment.id, so a per-row "model card exists?" check isn't
# possible — the doc link goes to the lookup page instead of a specific
# card. See Docs/Teams/Remediation pages for the same underlying gap.
# =========================================================================

@router.get("/admin/models", response_class=HTMLResponse)
def admin_models_page():
    body = """
<div id="page-content" hidden>
  <div class="page-max">
    <h1 style="font-size:var(--text-lg);margin-bottom:2px">Model Registry</h1>
    <p class="text-secondary" style="font-size:var(--text-sm);margin-bottom:var(--space-5)">
      Every model currently reachable on the platform &mdash; core services and self-service deployments.
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
  async function loadRegistry() {
    const body = document.getElementById('registry-body');
    body.innerHTML = UI.skeletonRows(5, 4);
    try {
      const [models, deployments] = await Promise.all([Api.get('/models/status'), Api.get('/deployments')]);
      const rows = [];
      models.forEach(m => rows.push({ name: m.name, task: m.task, status: m.status }));
      deployments.forEach(d => rows.push({ name: d.name, task: d.task_type, status: d.status }));
      if (!rows.length) {
        body.innerHTML = '<tr><td colspan="5">' + UI.emptyState('No models registered yet', 'Deploy a model from the Deployments page to see it here.') + '</td></tr>';
        return;
      }
      body.innerHTML = rows.map(r =>
        '<tr><td>' + UI.escapeHtml(r.name) + '</td><td>' + UI.escapeHtml(r.task) + '</td>' +
        '<td>' + UI.badge('huggingface', 'neutral') + '</td><td>' + UI.statusBadge(r.status) + '</td>' +
        '<td><a class="link-secondary" style="font-size:var(--text-xs)" href="/admin/docs">Look up documentation &rarr;</a></td></tr>'
      ).join('');
    } catch (e) {
      body.innerHTML = '<tr><td colspan="5">' + UI.errorState(e.message, loadRegistry) + '</td></tr>';
    }
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

    <div class="table-wrap" style="margin-bottom:var(--space-5)">
      <table class="table">
        <thead><tr><th>Deployment</th><th>Model</th><th>Task</th><th>Status</th><th>Replicas</th><th>Managed by</th></tr></thead>
        <tbody id="deployments-body"></tbody>
      </table>
    </div>

    <div class="section-label">Deploy a model</div>
    <div class="card">
      <form id="deploy-form" novalidate>
        <div class="field"><label class="field-label" for="dp-model">HuggingFace model name</label><input class="input" id="dp-model" placeholder="e.g. distilbert-base-uncased-finetuned-sst-2-english" required></div>
        <div class="field">
          <label class="field-label" for="dp-task">Task</label>
          <select class="select" id="dp-task">
            <option value="sentiment-analysis">Sentiment analysis</option>
            <option value="zero-shot-classification">Zero-shot classification</option>
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
      const [models, deployments] = await Promise.all([Api.get('/models/status'), Api.get('/deployments')]);
      const rows = [];
      models.forEach(m => rows.push({ name: m.name, model: m.model, task: m.task, status: m.status, replicas: '—', managed: 'core service' }));
      deployments.forEach(d => rows.push({ name: d.name, model: d.model_name, task: d.task_type, status: d.status, replicas: d.ready + '/' + d.desired, managed: 'platform' }));
      if (!rows.length) {
        body.innerHTML = '<tr><td colspan="6">' + UI.emptyState('No deployments yet', 'Use the form below to deploy your first model.') + '</td></tr>';
        return;
      }
      body.innerHTML = rows.map(r =>
        '<tr><td>' + UI.escapeHtml(r.name) + '</td><td class="text-secondary">' + UI.escapeHtml(r.model || '—') + '</td><td>' + UI.escapeHtml(r.task) + '</td>' +
        '<td>' + UI.statusBadge(r.status) + '</td><td class="text-secondary">' + r.replicas + '</td><td>' + UI.badge(r.managed, 'neutral') + '</td></tr>'
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
      const [models, deployments] = await Promise.all([Api.get('/models/status'), Api.get('/deployments')]);
      let runningInstances = 0;
      const rows = [];
      models.forEach(m => {
        rows.push({ name: m.name, type: 'Core service', status: m.status, replicas: '—' });
        if (m.status === 'online') runningInstances += 1;
      });
      deployments.forEach(d => {
        rows.push({ name: d.name, type: 'Platform deployment', status: d.status, replicas: d.ready + '/' + d.desired });
        runningInstances += d.ready || 0;
      });
      document.getElementById('pod-count').textContent = runningInstances;
      if (!rows.length) {
        body.innerHTML = '<tr><td colspan="4">' + UI.emptyState('No services running', 'Deployed models will appear here.') + '</td></tr>';
        return;
      }
      body.innerHTML = rows.map(r =>
        '<tr><td>' + UI.escapeHtml(r.name) + '</td><td class="text-secondary">' + r.type + '</td><td>' + UI.statusBadge(r.status) + '</td><td class="text-secondary">' + r.replicas + '</td></tr>'
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
    <h1 style="font-size:var(--text-lg);margin-bottom:2px">API Keys</h1>
    <p class="text-secondary" style="font-size:var(--text-sm);margin-bottom:var(--space-5)">
      Workspaces you belong to and their keys. There's no platform-wide workspace list in the API &mdash;
      this shows workspaces your admin account is a member of.
    </p>
    <div id="workspaces-list"></div>
  </div>
</div>
<div class="auth-loading" id="loading-root">Loading&hellip;</div>
"""

    script = """
<script>
  async function loadWorkspaces() {
    const list = document.getElementById('workspaces-list');
    list.innerHTML = '<div class="card"><span class="skeleton skeleton-text" style="display:block;max-width:220px">&nbsp;</span></div>';
    try {
      const workspaces = await Api.get('/workspaces');
      if (!workspaces.length) {
        list.innerHTML = UI.emptyState('No workspaces yet', 'Create a team from the Teams page to bootstrap your first workspace.');
        return;
      }
      list.innerHTML = workspaces.map(renderWorkspaceCard).join('');
      workspaces.forEach(ws => loadKeysFor(ws.id));
    } catch (e) {
      list.innerHTML = UI.errorState(e.message, loadWorkspaces);
    }
  }

  function renderWorkspaceCard(ws) {
    return '<div class="card" style="margin-bottom:var(--space-3)">' +
      '<div class="card-header"><div><div class="card-title">' + UI.escapeHtml(ws.name) + '</div>' +
      (ws.description ? '<div class="card-subtitle">' + UI.escapeHtml(ws.description) + '</div>' : '') + '</div>' +
      '<button class="btn btn-secondary btn-sm" data-new-key="' + ws.id + '" type="button">New key</button></div>' +
      '<div id="keys-for-' + ws.id + '"><span class="skeleton skeleton-text" style="display:block;max-width:180px">&nbsp;</span></div>' +
      '</div>';
  }

  async function loadKeysFor(wsId) {
    const el = document.getElementById('keys-for-' + wsId);
    try {
      const keys = await Api.get('/workspaces/' + wsId + '/api-keys');
      renderKeys(wsId, keys);
    } catch (e) {
      el.innerHTML = UI.errorState(e.message);
    }
    const btn = document.querySelector('[data-new-key="' + wsId + '"]');
    if (btn) btn.addEventListener('click', () => openNewKeyModal(wsId));
  }

  function renderKeys(wsId, keys) {
    const el = document.getElementById('keys-for-' + wsId);
    if (!keys.length) {
      el.innerHTML = '<div class="text-muted" style="font-size:var(--text-sm);padding:.3rem 0">No keys yet</div>';
      return;
    }
    el.innerHTML = keys.map(k =>
      '<div style="display:flex;justify-content:space-between;align-items:center;padding:.4rem 0;border-bottom:1px solid var(--color-border-subtle)">' +
      '<div><span style="font-size:var(--text-sm)">' + UI.escapeHtml(k.name) + '</span> <span class="text-muted" style="font-size:var(--text-xs)">' +
      UI.escapeHtml(k.prefix) + '&hellip; &middot; ' + UI.fmtDate(k.created_at) +
      (k.last_used_at ? ' &middot; last used ' + UI.timeAgo(k.last_used_at) : ' &middot; never used') + '</span></div>' +
      '<button class="btn btn-danger btn-sm" data-revoke-key="' + wsId + ':' + k.id + '" data-name="' + UI.escapeHtml(k.name) + '" type="button">Revoke</button>' +
      '</div>'
    ).join('');
    el.querySelectorAll('[data-revoke-key]').forEach(btn => {
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
      loadKeysFor(wsId);
    } catch (e) {
      UI.toast(e.message || 'Could not revoke key', 'danger');
    }
  }

  function openNewKeyModal(wsId) {
    const overlay = UI.openModal({
      title: 'New API key',
      bodyHtml: `
        <form id="new-key-form" novalidate>
          <div class="field"><label class="field-label" for="nk-name">Key name</label><input class="input" id="nk-name" placeholder="e.g. production, ci-cd" required></div>
          <div class="field-error" id="nk-error" role="alert"></div>
        </form>`,
      footerHtml: `<button class="btn btn-ghost" id="nk-cancel" type="button">Cancel</button>
                   <button class="btn btn-primary" id="nk-submit" type="submit" form="new-key-form">Generate key</button>`,
    });
    overlay.querySelector('#nk-cancel').addEventListener('click', UI.closeModal);
    overlay.querySelector('#new-key-form').addEventListener('submit', async (e) => {
      e.preventDefault();
      const errorEl = overlay.querySelector('#nk-error');
      const name = overlay.querySelector('#nk-name').value.trim();
      if (!name) { errorEl.textContent = 'Give the key a name.'; return; }
      try {
        const result = await Api.post('/workspaces/' + wsId + '/api-keys', { name });
        UI.closeModal();
        showRawKey(result);
        loadKeysFor(wsId);
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
      try {
        await navigator.clipboard.writeText(input.value);
        UI.toast('Copied to clipboard', 'success');
      } catch (e) {
        input.select();
        UI.toast('Could not auto-copy — key is selected, press Ctrl/Cmd+C', 'info');
      }
    });
  }
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
