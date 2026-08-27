"""
Team-member HTML pages (spec §9/§10): Overview, Models, Tickets, API Keys.

Wired to /auth/me, /tickets, /tickets/my, /workspaces/{id}/api-keys,
/deployments, /models/status — the endpoints a non-admin user can actually
call. See the note above _MODELS_SCOPE_NOTE below for a real gap this ran
into: there is no endpoint that lets a non-admin discover which teams they
belong to or which deployments their team has been granted, so "assigned
models" can't be scoped per-team from the frontend today. This shows the
same platform-wide model list every user sees rather than fabricate a
filter with no data behind it.

API keys live on a legacy Workspace container that a freshly admin-created
user has no membership in. This page bootstraps a personal workspace via
the existing POST /workspaces the first time the user actually creates a
key (never just from viewing the page) — same pattern used in the admin
Teams page for team creation.
"""

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

from backend.app.routers._page_fragments import (
    CHART_JS_CDN, MONITORING_CSS, MONITORING_BODY, MONITORING_SCRIPTS_EXTRA,
    DRIFT_BODY, DRIFT_SCRIPTS_EXTRA,
    DOCS_BODY, DOCS_SCRIPTS_EXTRA,
    SETTINGS_BODY, SETTINGS_SCRIPTS_EXTRA,
    _STATIC_V,
)

router = APIRouter()

_ASSETS = """<link rel="stylesheet" href="/static/css/tokens.css">
<link rel="stylesheet" href="/static/css/base.css">
<link rel="stylesheet" href="/static/css/components.css">
<link rel="stylesheet" href="/static/css/shell.css">
<link rel="stylesheet" href="/static/css/light-theme.css">"""

_SCRIPTS = f"""<script src="/static/js/api.js"></script>
<script src="/static/js/shell.js"></script>
<script src="/static/js/ui.js"></script>
<script src="/static/js/predictor.js?v={_STATIC_V}"></script>"""


def _boot_script(active_path: str, breadcrumb_label: str, on_ready: str) -> str:
    """Standard member-page bootstrap: auth -> shell mount -> loader. No
    admin gate — any authenticated, non-force-password-change user can
    view /app/*."""
    return """
<script>
  (async function boot() {
    const user = await Api.requireAuth();
    if (!user) return;
    Shell.mount({
      user: user,
      activePath: '""" + active_path + """',
      breadcrumbs: [{label: 'Home', href: '/app'}""" + (
        ", {label: '" + breadcrumb_label + "'}" if breadcrumb_label else ""
    ) + """],
    });
    """ + on_ready + """
  })();
</script>"""


# =========================================================================
# Overview — /app
# =========================================================================

@router.get("/app", response_class=HTMLResponse)
def member_overview_page():
    body = """
<div id="page-content" hidden>
  <div class="page-max">
    <h1 id="greeting" style="font-size:var(--text-lg);margin-bottom:var(--space-5)">Loading…</h1>

    <div class="section-label" style="margin-top:0">My Teams</div>
    <div class="card-grid" id="teams-grid" style="margin-bottom:var(--space-6)"></div>

    <div class="card-header">
      <div class="section-label" style="margin:0">My Models</div>
      <a href="/app/models" class="link-secondary" style="font-size:var(--text-sm)">View all &rarr;</a>
    </div>
    <div class="card-grid" id="models-preview" style="margin-bottom:var(--space-6)"></div>

    <div class="card-header">
      <div class="section-label" style="margin:0">My tickets</div>
      <a href="/app/tickets" class="link-secondary" style="font-size:var(--text-sm)">View all &rarr;</a>
    </div>
    <div class="metric-row" id="ticket-metrics" style="margin-bottom:var(--space-5)"></div>
    <div class="card" id="recent-tickets-card" style="margin-bottom:var(--space-6)"></div>
  </div>
</div>
<div class="auth-loading" id="loading-root">Loading…</div>
"""

    script = """
<script>
  function greetingFor(user) {
    const h = new Date().getHours();
    const part = h < 12 ? 'Good morning' : h < 18 ? 'Good afternoon' : 'Good evening';
    return part + ', ' + (user.name || user.username);
  }

  function tile(value, label, variant) {
    return '<div class="metric-tile"><div class="metric-tile-value' + (variant ? ' is-' + variant : '') + '">' + value + '</div><div class="metric-tile-label">' + label + '</div></div>';
  }

  async function loadOverview(user) {
    document.getElementById('greeting').textContent = greetingFor(user);

    let teams = [];
    try {
      teams = await Api.get('/users/me/teams');
      renderTeams(teams);
    } catch (e) {
      document.getElementById('teams-grid').innerHTML = UI.errorState(e.message);
    }

    try {
      // Same teams list as renderTeams() above, reused rather than
      // re-fetched. If that first call failed, `teams` is still [], which
      // correctly falls through to the same no-access empty state below.
      await renderModelsPreview(teams);
    } catch (e) {
      document.getElementById('models-preview').innerHTML = UI.errorState(e.message);
    }

    try {
      const tickets = await Api.get('/tickets/my');
      renderTicketMetrics(tickets);
      renderRecentTickets(tickets);
    } catch (e) {
      document.getElementById('recent-tickets-card').innerHTML = UI.errorState(e.message);
    }
  }

  function renderTeams(teams) {
    const el = document.getElementById('teams-grid');
    if (!teams.length) {
      el.innerHTML = UI.emptyState('No teams yet', 'Ask your admin to add you to a team.');
      return;
    }
    el.innerHTML = teams.map(t =>
      '<a class="card" href="/app/teams/' + t.id + '" style="display:block;text-decoration:none;color:inherit">' +
      '<div class="card-title">' + UI.escapeHtml(t.name) + '</div>' +
      '<div class="card-subtitle">' + (t.description ? UI.escapeHtml(t.description) : '<span class="text-muted">No description</span>') + '</div>' +
      '<div class="text-secondary" style="font-size:var(--text-xs);margin-top:.6rem">' +
      t.model_count + ' model' + (t.model_count === 1 ? '' : 's') + ' &middot; ' + t.member_count + ' member' + (t.member_count === 1 ? '' : 's') +
      '</div></a>'
    ).join('');
  }

  function renderTicketMetrics(tickets) {
    const open = tickets.filter(t => t.status === 'open').length;
    const investigating = tickets.filter(t => t.status === 'investigating').length;
    const done = tickets.filter(t => t.status === 'resolved' || t.status === 'closed').length;
    document.getElementById('ticket-metrics').innerHTML =
      tile(open, 'Open', open > 0 ? 'warning' : undefined) +
      tile(investigating, 'Investigating') +
      tile(done, 'Resolved') +
      tile(tickets.length, 'Total filed');
  }

  function renderRecentTickets(tickets) {
    const card = document.getElementById('recent-tickets-card');
    if (!tickets.length) {
      card.innerHTML = UI.emptyState('No tickets yet', 'Filed an issue with a model? Track it here.');
      return;
    }
    card.innerHTML = tickets.slice(0, 5).map(t =>
      '<div style="display:flex;justify-content:space-between;align-items:center;gap:.75rem;padding:.5rem 0;border-bottom:1px solid var(--color-border-subtle)">' +
      '<div style="min-width:0"><div style="font-size:var(--text-sm);white-space:nowrap;overflow:hidden;text-overflow:ellipsis">' + UI.escapeHtml(t.title) + '</div>' +
      '<div class="text-muted" style="font-size:var(--text-xs)">' + UI.timeAgo(t.filed_at) + '</div></div>' +
      '<div style="display:flex;gap:.4rem;flex-shrink:0">' + UI.severityBadge(t.severity) + UI.statusBadge(t.status) + '</div>' +
      '</div>'
    ).join('');
  }

  async function renderModelsPreview(teams) {
    const el = document.getElementById('models-preview');
    if (!teams.length) {
      el.innerHTML = UI.emptyState("Your team hasn't been granted model access yet.", "Contact your admin.");
      return;
    }

    // Same source as /app/models: GET /teams/{id}/permissions across all
    // of the user's teams, deduped by deployment_id — not
    // /models/status + /deployments, which can't be scoped to what's
    // actually permitted (see /app/models for why). team_id/team_name
    // attached client-side since the permissions endpoint itself doesn't
    // echo back which team it was queried for.
    const perTeam = await Promise.allSettled(
      teams.map(t => Api.get('/teams/' + t.id + '/permissions').then(perms =>
        perms.map(p => Object.assign({}, p, { team_id: t.id, team_name: t.name }))
      ))
    );
    const byDeployment = new Map();
    perTeam.forEach(result => {
      if (result.status !== 'fulfilled') return;
      result.value.forEach(p => {
        if (!byDeployment.has(p.deployment_id)) byDeployment.set(p.deployment_id, p);
      });
    });
    const rows = Array.from(byDeployment.values());

    if (!rows.length) {
      el.innerHTML = UI.emptyState("Your team hasn't been granted model access yet.", "Contact your admin.");
      return;
    }
    el.innerHTML = rows.slice(0, 3).map(r =>
      '<div class="card">' +
      '<div class="card-title">' + UI.escapeHtml(r.model_name) + '</div>' +
      '<div class="card-subtitle">' + UI.escapeHtml(r.team_name) + '</div>' +
      '<div style="margin:.5rem 0">' + UI.statusBadge(r.status) + '</div>' +
      (r.can_predict
        ? '<a class="link-secondary" style="font-size:var(--text-xs)" href="/app/teams/' + r.team_id + '">Get API key &rarr;</a>'
        : UI.badge('View only', 'neutral')
      ) +
      '</div>'
    ).join('');
  }
</script>"""

    ready = "loadOverview(user);"

    html = (
        "<!DOCTYPE html>\n<html lang=\"en\">\n<head>\n<meta charset=\"UTF-8\">\n"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">\n"
        "<title>Overview — Vela</title>\n" + _ASSETS + "\n</head>\n<body>\n"
        + body
        + "\n" + _SCRIPTS + "\n" + script
        + _boot_script("/app", "", ready)
        + "\n</body>\n</html>"
    )
    return html


# =========================================================================
# Team detail — /app/teams/{team_id}
#
# One page serves every team_id — the id is read from the URL client-side
# and used to fetch GET /teams/{id} (name/description/workspace_id) and
# GET /teams/{id}/permissions (the model list, now enriched with
# task_type/status in services/teams.py). "Get API key" generates a key
# scoped to this exact team_id + deployment_id via
# POST /workspaces/{workspace_id}/api-keys — the workspace_id comes
# straight from GET /teams/{id}, so there's no ambiguity about which
# workspace a member's key should land in.
# =========================================================================

@router.get("/app/teams/{team_id}", response_class=HTMLResponse)
def member_team_detail_page(team_id: int):
    body = """
<div id="page-content" hidden>
  <div class="page-max">
    <a href="/app" class="link-secondary" style="font-size:var(--text-sm)">&larr; My Teams</a>
    <h1 id="team-name" style="font-size:var(--text-lg);margin:.5rem 0 2px">Loading&hellip;</h1>
    <p id="team-description" class="text-secondary" style="font-size:var(--text-sm);margin-bottom:var(--space-5)"></p>

    <div class="section-label" style="margin-top:0">Models</div>
    <div class="table-wrap">
      <table class="table">
        <thead><tr><th>Model</th><th>Task</th><th>Status</th><th></th></tr></thead>
        <tbody id="models-body"></tbody>
      </table>
    </div>
  </div>
</div>
<div class="auth-loading" id="loading-root">Loading&hellip;</div>
"""

    script = """
<script>
  const TEAM_ID = location.pathname.split('/')[3];
  let TEAM_WORKSPACE_ID = null;
  let TEAM_NAME = '';

  async function loadTeam() {
    try {
      const team = await Api.get('/teams/' + TEAM_ID);
      TEAM_NAME = team.name;
      TEAM_WORKSPACE_ID = team.workspace_id;
      document.getElementById('team-name').textContent = team.name;
      document.getElementById('team-description').textContent = team.description || 'No description';
      document.title = team.name + ' — Vela';
      const crumb = document.querySelector('.shell-breadcrumb-current');
      if (crumb) crumb.textContent = team.name;
      renderModels(team.permissions || []);
    } catch (e) {
      document.getElementById('models-body').innerHTML = '<tr><td colspan="4">' + UI.errorState(e.message, loadTeam) + '</td></tr>';
    }
  }

  let teamPerms = [];

  function renderModels(perms) {
    // Admin "Disable" (/admin/models) hides a model from members
    // entirely rather than showing it greyed out — the admin teams-page
    // (/admin/teams-page) shows these same permission rows unfiltered,
    // since an admin still needs to see/manage a disabled model's grants.
    perms = perms.filter(p => p.is_active !== false);
    teamPerms = perms;
    const body = document.getElementById('models-body');
    if (!perms.length) {
      body.innerHTML = '<tr><td colspan="4">' + UI.emptyState('No models yet', 'This team has not been granted access to any models.') + '</td></tr>';
      return;
    }
    body.innerHTML = perms.map((p, idx) => {
      const uid = 'd' + p.deployment_id;
      const lastCell = p.can_predict
        ? '<button class="btn btn-secondary btn-sm" data-get-key="' + idx + '" type="button">Get API key</button>' +
          '<div style="margin-top:.6rem;max-width:280px">' + Predictor.render(uid, TEAM_ID, p.deployment_id, p.input_type, p.input_schema) + '</div>'
        : UI.badge('View only', 'neutral');
      return '<tr>' +
        '<td>' + UI.escapeHtml(p.model_name) + '</td>' +
        '<td>' + UI.escapeHtml(p.task_type) + '</td>' +
        '<td>' + UI.statusBadge(p.status) + '</td>' +
        '<td>' + lastCell + '</td>' +
        '</tr>';
    }).join('');
    body.querySelectorAll('[data-get-key]').forEach(btn => {
      const idx = parseInt(btn.dataset.getKey, 10);
      btn.addEventListener('click', () => getApiKey(teamPerms[idx], btn));
    });
    perms.forEach(p => {
      if (!p.can_predict) return;
      Predictor.wire('d' + p.deployment_id, TEAM_ID, p.deployment_id, p.input_type, p.input_schema);
    });
  }

  async function getApiKey(perm, btn) {
    btn.disabled = true;
    const originalLabel = btn.textContent;
    btn.textContent = 'Generating…';
    try {
      const result = await Api.post('/workspaces/' + TEAM_WORKSPACE_ID + '/api-keys', {
        name: TEAM_NAME + ': ' + perm.model_name,
        team_id: parseInt(TEAM_ID, 10),
        deployment_id: perm.deployment_id,
      });
      showRawKey(result);
    } catch (e) {
      UI.toast(e.message || 'Could not generate key', 'danger');
    } finally {
      btn.disabled = false;
      btn.textContent = originalLabel;
    }
  }

  function showRawKey(result) {
    const overlay = UI.openModal({
      title: 'Copy your API key',
      bodyHtml: `
        <div class="alert alert-warning" style="margin-bottom:.75rem">
          <div><div class="alert-title">Shown once</div><div class="alert-body">This key will not be shown again — copy it now and store it somewhere safe. It only works for this model.</div></div>
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
</script>"""

    ready = "loadTeam();"

    html = (
        "<!DOCTYPE html>\n<html lang=\"en\">\n<head>\n<meta charset=\"UTF-8\">\n"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">\n"
        "<title>Team — Vela</title>\n" + _ASSETS + "\n</head>\n<body>\n"
        + body
        + "\n" + _SCRIPTS + "\n" + script
        + _boot_script("/app/teams/" + str(team_id), "Team", ready)
        + "\n</body>\n</html>"
    )
    return html


# =========================================================================
# Models — /app/models
# =========================================================================

@router.get("/app/models", response_class=HTMLResponse)
def member_models_page():
    body = """
<div id="page-content" hidden>
  <div class="page-max">
    <h1 style="font-size:var(--text-lg);margin-bottom:2px">Models</h1>
    <p class="text-secondary" style="font-size:var(--text-sm);margin-bottom:var(--space-5)">
      Models your teams have been granted access to.
    </p>
    <div class="card-grid" id="models-grid"></div>
  </div>
</div>
<div class="auth-loading" id="loading-root">Loading&hellip;</div>
"""

    script = """
<script>
  // Scoped to what the user's teams actually have permission for — built
  // straight from GET /teams/{id}/permissions across all of GET
  // /users/me/teams, not from /models/status + /deployments. Those two
  // can't be filtered this way even in principle: /deployments (k8s)
  // never carries a DB deployment_id at all, and the two hardcoded core
  // services in /models/status aren't Deployment rows, so they can never
  // have a TeamModelPermission grant either way. The permissions endpoint
  // already carries deployment_id, model_name, task_type and status
  // directly, so it's used as the source of truth rather than attempting
  // a join that the other two endpoints don't have the data to support.
  //
  // The prediction tester's API key comes from sessionStorage, scoped
  // per team+deployment (see predictor.js) — set inline from the tester
  // itself now, no detour through /app/teams/{id} required. Never
  // routed through the shared Api helper — that attaches the JWT and
  // treats any 401 as "session expired", which would be wrong for a
  // bad/missing model API key.
  let modelRows = [];

  async function loadModels() {
    const grid = document.getElementById('models-grid');
    grid.innerHTML = '<div class="card"><span class="skeleton skeleton-text">&nbsp;</span></div>'.repeat(3);
    try {
      const teams = await Api.get('/users/me/teams');
      if (!teams.length) {
        renderNoAccess();
        return;
      }

      const perTeam = await Promise.allSettled(
        teams.map(t => Api.get('/teams/' + t.id + '/permissions').then(perms =>
          perms.map(p => Object.assign({}, p, { team_id: t.id, team_name: t.name }))
        ))
      );

      const byDeployment = new Map();
      perTeam.forEach(result => {
        if (result.status !== 'fulfilled') return;
        result.value.forEach(p => {
          // Admin "Disable" (/admin/models) hides a model from members
          // entirely — see the matching filter on /app/teams/{id}.
          if (p.is_active === false) return;
          if (!byDeployment.has(p.deployment_id)) byDeployment.set(p.deployment_id, p);
        });
      });
      modelRows = Array.from(byDeployment.values());

      if (!modelRows.length) {
        renderNoAccess();
        return;
      }

      grid.innerHTML = modelRows.map(renderCard).join('');
      modelRows.forEach(r => {
        if (!r.can_predict) return;
        Predictor.wire('d' + r.deployment_id, r.team_id, r.deployment_id, r.input_type, r.input_schema);
      });
    } catch (e) {
      grid.innerHTML = UI.errorState(e.message, loadModels);
    }
  }

  function renderNoAccess() {
    document.getElementById('models-grid').innerHTML = UI.emptyState(
      "Your team hasn't been granted model access yet.",
      "Contact your admin."
    );
  }

  function renderCard(r) {
    const testerHtml = r.can_predict
      ? Predictor.render('d' + r.deployment_id, r.team_id, r.deployment_id, r.input_type, r.input_schema)
      : UI.badge('View only', 'neutral');

    return '<div class="card">' +
      '<div class="card-title">' + UI.escapeHtml(r.model_name) + '</div>' +
      '<div class="card-subtitle">' + UI.escapeHtml(r.task_type) + ' &middot; ' + UI.escapeHtml(r.team_name) + '</div>' +
      '<div style="margin:.5rem 0">' + UI.statusBadge(r.status) + '</div>' +
      '<a class="link-secondary" style="font-size:var(--text-xs)" href="/app/tickets?model=' + encodeURIComponent(r.model_name) + '">Report an issue &rarr;</a>' +
      '<div style="margin-top:.75rem;padding-top:.75rem;border-top:1px solid var(--color-border-subtle)">' + testerHtml + '</div>' +
      '</div>';
  }
</script>"""

    ready = "loadModels();"

    html = (
        "<!DOCTYPE html>\n<html lang=\"en\">\n<head>\n<meta charset=\"UTF-8\">\n"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">\n"
        "<title>Models — Vela</title>\n" + _ASSETS + "\n</head>\n<body>\n"
        + body
        + "\n" + _SCRIPTS + "\n" + script
        + _boot_script("/app/models", "My Models", ready)
        + "\n</body>\n</html>"
    )
    return html


# =========================================================================
# Tickets — /app/tickets
# =========================================================================

@router.get("/app/tickets", response_class=HTMLResponse)
def member_tickets_page():
    body = """
<div id="page-content" hidden>
  <div class="page-max">
    <div class="card-header">
      <h1 style="font-size:var(--text-lg)">My tickets</h1>
      <button class="btn btn-primary" id="new-ticket-btn" type="button">New ticket</button>
    </div>
    <div class="table-wrap">
      <table class="table">
        <thead>
          <tr><th>Title</th><th>Type</th><th>Severity</th><th>Status</th><th>Filed</th><th></th></tr>
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
  let myTickets = [];

  async function loadTickets() {
    const body = document.getElementById('tickets-body');
    body.innerHTML = UI.skeletonRows(6, 4);
    try {
      myTickets = await Api.get('/tickets/my');
      renderTickets();
    } catch (e) {
      body.innerHTML = '<tr><td colspan="6">' + UI.errorState(e.message, loadTickets) + '</td></tr>';
    }
  }

  function renderTickets() {
    const body = document.getElementById('tickets-body');
    if (!myTickets.length) {
      body.innerHTML = '<tr><td colspan="6">' + UI.emptyState('No tickets filed yet', 'Run into a problem with a model? File a ticket and track it here.') + '</td></tr>';
      return;
    }
    body.innerHTML = myTickets.map(t =>
      '<tr class="is-interactive" data-open-ticket="' + t.id + '">' +
      '<td style="max-width:260px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">' + UI.escapeHtml(t.title) + '</td>' +
      '<td>' + UI.badge(t.ticket_type, 'neutral') + '</td>' +
      '<td>' + UI.severityBadge(t.severity) + '</td>' +
      '<td>' + UI.statusBadge(t.status) + '</td>' +
      '<td class="text-secondary">' + UI.timeAgo(t.filed_at) + '</td>' +
      '<td><button class="btn btn-ghost btn-sm" type="button">View</button></td>' +
      '</tr>'
    ).join('');
    body.querySelectorAll('[data-open-ticket]').forEach(row => {
      row.addEventListener('click', () => viewTicket(row.dataset.openTicket));
    });
  }

  function viewTicket(id) {
    const t = myTickets.find(x => String(x.id) === String(id));
    if (!t) return;
    const overlay = UI.openModal({
      title: t.title,
      bodyHtml: `
        <div style="margin-bottom:.75rem">${UI.severityBadge(t.severity)} ${UI.statusBadge(t.status)} ${UI.badge(t.ticket_type, 'neutral')}</div>
        <div class="text-secondary" style="font-size:var(--text-sm);white-space:pre-wrap;margin-bottom:.75rem">${UI.escapeHtml(t.description)}</div>
        ${t.evidence ? '<div class="section-label">Evidence</div><div class="text-secondary" style="font-size:var(--text-xs);white-space:pre-wrap;margin-bottom:.75rem">' + UI.escapeHtml(t.evidence) + '</div>' : ''}
        <div class="text-muted" style="font-size:var(--text-xs);margin-bottom:.75rem">Filed ${UI.fmtDate(t.filed_at)}</div>
        ${t.resolution_note ? '<div class="alert alert-info"><div><div class="alert-title">Resolution</div><div class="alert-body">' + UI.escapeHtml(t.resolution_note) + '</div></div></div>' : ''}
      `,
      footerHtml: `<button class="btn btn-secondary" id="tk-close" type="button">Close</button>`,
    });
    overlay.querySelector('#tk-close').addEventListener('click', UI.closeModal);
  }

  function openNewTicketModal(prefill) {
    const overlay = UI.openModal({
      title: 'New ticket',
      bodyHtml: `
        <form id="new-ticket-form" novalidate>
          <div class="field"><label class="field-label" for="nt-title">Title</label><input class="input" id="nt-title" required></div>
          <div class="field"><label class="field-label" for="nt-desc">Description</label><textarea class="textarea" id="nt-desc" rows="3" required>${prefill ? 'Regarding model: ' + UI.escapeHtml(prefill) + '\\n\\n' : ''}</textarea></div>
          <div class="field">
            <label class="field-label" for="nt-type">Type</label>
            <select class="select" id="nt-type">
              <option value="bug">Bug</option>
              <option value="anomaly">Anomaly</option>
              <option value="feedback">Feedback</option>
              <option value="other">Other</option>
            </select>
          </div>
          <div class="field">
            <label class="field-label" for="nt-severity">Severity</label>
            <select class="select" id="nt-severity">
              <option value="low">Low</option>
              <option value="medium" selected>Medium</option>
              <option value="high">High</option>
              <option value="critical">Critical</option>
            </select>
          </div>
          <div class="field"><label class="field-label" for="nt-evidence">Evidence (optional)</label><textarea class="textarea" id="nt-evidence" rows="2" placeholder="Logs, example inputs, screenshots described…"></textarea></div>
          <div class="field-error" id="nt-error" role="alert"></div>
        </form>`,
      footerHtml: `<button class="btn btn-ghost" id="nt-cancel" type="button">Cancel</button>
                   <button class="btn btn-primary" id="nt-submit" type="submit" form="new-ticket-form">File ticket</button>`,
    });
    overlay.querySelector('#nt-cancel').addEventListener('click', UI.closeModal);
    overlay.querySelector('#new-ticket-form').addEventListener('submit', async (e) => {
      e.preventDefault();
      const errorEl = overlay.querySelector('#nt-error');
      const title = overlay.querySelector('#nt-title').value.trim();
      const description = overlay.querySelector('#nt-desc').value.trim();
      const ticket_type = overlay.querySelector('#nt-type').value;
      const severity = overlay.querySelector('#nt-severity').value;
      const evidence = overlay.querySelector('#nt-evidence').value.trim();
      if (!title || !description) {
        errorEl.textContent = 'Title and description are required.';
        return;
      }
      try {
        await Api.post('/tickets', { title, description, ticket_type, severity, evidence });
        UI.toast('Ticket filed', 'success');
        UI.closeModal();
        loadTickets();
      } catch (err) {
        errorEl.textContent = err.message || 'Could not file ticket.';
      }
    });
  }

  document.getElementById('new-ticket-btn').addEventListener('click', () => openNewTicketModal());

  // Deep link from a model card: /app/tickets?model=NAME opens the form pre-filled.
  const params = new URLSearchParams(location.search);
  const modelParam = params.get('model');
  if (modelParam) {
    setTimeout(() => openNewTicketModal(modelParam), 0);
  }
</script>"""

    ready = "loadTickets();"

    html = (
        "<!DOCTYPE html>\n<html lang=\"en\">\n<head>\n<meta charset=\"UTF-8\">\n"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">\n"
        "<title>Tickets — Vela</title>\n" + _ASSETS + "\n</head>\n<body>\n"
        + body
        + "\n" + _SCRIPTS + "\n" + script
        + _boot_script("/app/tickets", "Tickets", ready)
        + "\n</body>\n</html>"
    )
    return html


# =========================================================================
# API Keys — /app/api-keys
# =========================================================================

@router.get("/app/api-keys", response_class=HTMLResponse)
def member_api_keys_page():
    body = """
<div id="page-content" hidden>
  <div class="page-max">
    <h1 style="font-size:var(--text-lg);margin-bottom:2px">API keys</h1>
    <p class="text-secondary" style="font-size:var(--text-sm);margin-bottom:var(--space-5)">
      Keys are scoped to one model each and generated from that model's team page. Shown in full only once, at creation.
    </p>
    <div id="keys-list"></div>
  </div>
</div>
<div class="auth-loading" id="loading-root">Loading&hellip;</div>
"""

    script = """
<script>
  // Members don't self-provision a workspace here — that flow (an
  // on-demand POST /workspaces) could fail server-side with no graceful
  // fallback. Workspace access now comes from being added to a team (see
  // services/teams.py add_team_member); this page just reflects it.
  //
  // A member can in principle belong to more than one workspace, so keys
  // are fetched per-workspace and merged; keyWorkspaceMap remembers which
  // workspace each key came from, since DELETE needs that workspace_id.
  let keyWorkspaceMap = {};

  function noWorkspaceState() {
    document.getElementById('keys-list').innerHTML = UI.emptyState(
      'No workspace access yet',
      'Ask your admin to provision access.'
    );
  }

  async function loadKeys() {
    const list = document.getElementById('keys-list');
    list.innerHTML = '<div class="card"><span class="skeleton skeleton-text" style="display:block;max-width:220px">&nbsp;</span></div>';
    try {
      const workspaces = await Api.get('/workspaces');
      if (!workspaces.length) {
        noWorkspaceState();
        return;
      }
      keyWorkspaceMap = {};
      const perWorkspace = await Promise.all(workspaces.map(ws => Api.get('/workspaces/' + ws.id + '/api-keys')));
      const allKeys = [];
      perWorkspace.forEach((keys, i) => {
        keys.forEach(k => {
          keyWorkspaceMap[k.id] = workspaces[i].id;
          allKeys.push(k);
        });
      });
      renderKeys(allKeys);
    } catch (e) {
      list.innerHTML = UI.errorState(e.message, loadKeys);
    }
  }

  function renderKeys(keys) {
    const list = document.getElementById('keys-list');
    if (!keys.length) {
      list.innerHTML = UI.emptyState("No API keys yet", "Generate one from a team's page — see My Teams on the Overview page.");
      return;
    }

    const groups = {};
    const ungrouped = [];
    keys.forEach(k => {
      if (k.team_id) {
        const label = k.team_name || ('Team #' + k.team_id);
        (groups[label] = groups[label] || []).push(k);
      } else {
        ungrouped.push(k);
      }
    });

    let html = '';
    Object.keys(groups).sort().forEach(label => {
      html += '<div class="section-label" style="margin-top:var(--space-5)">' + UI.escapeHtml(label) + '</div>';
      html += '<div class="card">' + groups[label].map(renderKeyRow).join('') + '</div>';
    });
    if (ungrouped.length) {
      html += '<div class="section-label" style="margin-top:var(--space-5)">Other keys</div>';
      html += '<div class="card">' + ungrouped.map(renderKeyRow).join('') + '</div>';
    }
    list.innerHTML = html;

    list.querySelectorAll('[data-revoke]').forEach(btn => {
      btn.addEventListener('click', () => revokeKey(btn.dataset.revoke, btn.dataset.name));
    });
  }

  function renderKeyRow(k) {
    return '<div style="display:flex;justify-content:space-between;align-items:center;padding:.5rem 0;border-bottom:1px solid var(--color-border-subtle)">' +
      '<div style="min-width:0">' +
      '<div style="font-size:var(--text-sm);font-weight:600">' + UI.escapeHtml(k.model_name || k.name || 'Unnamed key') + '</div>' +
      '<div class="text-muted" style="font-size:var(--text-xs)">' +
      UI.escapeHtml(k.prefix) + '&hellip; &middot; created ' + UI.fmtDate(k.created_at) +
      (k.last_used_at ? ' &middot; last used ' + UI.timeAgo(k.last_used_at) : ' &middot; never used') +
      '</div></div>' +
      '<button class="btn btn-danger btn-sm" data-revoke="' + k.id + '" data-name="' + UI.escapeHtml(k.name || k.model_name || '') + '" type="button">Revoke</button>' +
      '</div>';
  }

  async function revokeKey(id, name) {
    if (!confirm('Revoke "' + name + '"? Anything using this key will stop working immediately.')) return;
    const wsId = keyWorkspaceMap[id];
    try {
      await Api.del('/workspaces/' + wsId + '/api-keys/' + id);
      UI.toast('Key revoked', 'success');
      loadKeys();
    } catch (e) {
      UI.toast(e.message || 'Could not revoke key', 'danger');
    }
  }
</script>"""

    ready = "loadKeys();"

    html = (
        "<!DOCTYPE html>\n<html lang=\"en\">\n<head>\n<meta charset=\"UTF-8\">\n"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">\n"
        "<title>API Keys — Vela</title>\n" + _ASSETS + "\n</head>\n<body>\n"
        + body
        + "\n" + _SCRIPTS + "\n" + script
        + _boot_script("/app/api-keys", "API Keys", ready)
        + "\n</body>\n</html>"
    )
    return html


# =========================================================================
# Monitoring — /app/monitoring
# =========================================================================

@router.get("/app/monitoring", response_class=HTMLResponse)
def member_monitoring_page():
    ready = "Monitoring.start({role: 'member'});"

    html = (
        "<!DOCTYPE html>\n<html lang=\"en\">\n<head>\n<meta charset=\"UTF-8\">\n"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">\n"
        "<title>Model Health — Vela</title>\n" + _ASSETS + "\n" + CHART_JS_CDN + "\n" + MONITORING_CSS + "\n</head>\n<body>\n"
        + MONITORING_BODY
        + "\n" + _SCRIPTS + "\n" + MONITORING_SCRIPTS_EXTRA
        + _boot_script("/app/monitoring", "Monitoring", ready)
        + "\n</body>\n</html>"
    )
    return html


# =========================================================================
# Drift — /app/drift
# =========================================================================

@router.get("/app/drift", response_class=HTMLResponse)
def member_drift_page():
    ready = "Drift.start({role: 'member', actionHrefFor: (e) => '/app/tickets?model=' + encodeURIComponent(e ? e.label : ''), actionLabel: 'File a ticket'});"

    html = (
        "<!DOCTYPE html>\n<html lang=\"en\">\n<head>\n<meta charset=\"UTF-8\">\n"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">\n"
        "<title>Drift — Vela</title>\n" + _ASSETS + "\n" + CHART_JS_CDN + "\n" + MONITORING_CSS + "\n</head>\n<body>\n"
        + DRIFT_BODY
        + "\n" + _SCRIPTS + "\n" + DRIFT_SCRIPTS_EXTRA
        + _boot_script("/app/drift", "Drift", ready)
        + "\n</body>\n</html>"
    )
    return html


# =========================================================================
# Documentation — /app/docs
# =========================================================================

@router.get("/app/docs", response_class=HTMLResponse)
def member_docs_page():
    ready = "Docs.start({role: 'member'});"

    html = (
        "<!DOCTYPE html>\n<html lang=\"en\">\n<head>\n<meta charset=\"UTF-8\">\n"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">\n"
        "<title>Documentation — Vela</title>\n" + _ASSETS + "\n</head>\n<body>\n"
        + DOCS_BODY
        + "\n" + _SCRIPTS + "\n" + DOCS_SCRIPTS_EXTRA
        + _boot_script("/app/docs", "Documentation", ready)
        + "\n</body>\n</html>"
    )
    return html


# =========================================================================
# Settings — /app/settings
# =========================================================================

@router.get("/app/settings", response_class=HTMLResponse)
def member_settings_page():
    ready = "Settings.start(user);"

    html = (
        "<!DOCTYPE html>\n<html lang=\"en\">\n<head>\n<meta charset=\"UTF-8\">\n"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">\n"
        "<title>Settings — Vela</title>\n" + _ASSETS + "\n</head>\n<body>\n"
        + SETTINGS_BODY
        + "\n" + _SCRIPTS + "\n" + SETTINGS_SCRIPTS_EXTRA
        + _boot_script("/app/settings", "Settings", ready)
        + "\n</body>\n</html>"
    )
    return html
