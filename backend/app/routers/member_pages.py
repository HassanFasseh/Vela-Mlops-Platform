"""
Team-member HTML pages (spec §9/§10): Overview, Models, Tickets, API Keys.

Wired to /auth/me, /tickets, /tickets/my, /workspaces/{id}/api-keys,
/deployments, /models/status - the endpoints a non-admin user can actually
call. See the note above _MODELS_SCOPE_NOTE below for a real gap this ran
into: there is no endpoint that lets a non-admin discover which teams they
belong to or which deployments their team has been granted, so "assigned
models" can't be scoped per-team from the frontend today. This shows the
same platform-wide model list every user sees rather than fabricate a
filter with no data behind it.

API keys live on a legacy Workspace container that a freshly admin-created
user has no membership in. This page bootstraps a personal workspace via
the existing POST /workspaces the first time the user actually creates a
key (never just from viewing the page) - same pattern used in the admin
Teams page for team creation.
"""

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

from backend.app.routers._page_fragments import (
    DS_ASSETS, CHART_JS_CDN, MONITORING_CSS, MONITORING_BODY, MONITORING_SCRIPTS_EXTRA,
    DOCS_SCRIPTS_EXTRA,
    SETTINGS_SCRIPTS_EXTRA,
    _STATIC_V,
)

router = APIRouter()

_SCRIPTS = f"""<script src="/static/js/api.js?v={_STATIC_V}"></script>
<script src="/static/js/shell.js?v={_STATIC_V}"></script>
<script src="/static/js/ui.js?v={_STATIC_V}"></script>
<script src="/static/js/predictor.js?v={_STATIC_V}"></script>"""


def _boot_script(active_path: str, breadcrumb_label: str, on_ready: str) -> str:
    """Standard member-page bootstrap: auth -> shell mount -> loader. No
    admin gate - any authenticated, non-force-password-change user can
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
# Overview - /app
# =========================================================================

@router.get("/app", response_class=HTMLResponse)
def member_overview_page():
    body = """
<div id="page-content" hidden>
  <div class="page-max">
    <div class="page-header">
      <div>
        <h1 class="page-title" id="greeting">Loading…</h1>
        <div class="page-description">Your teams, models and tickets in one place.</div>
      </div>
    </div>

    <div class="card-header">
      <div class="section-label" style="margin:0">My Teams</div>
    </div>
    <div class="table-wrap" style="margin-bottom:var(--space-6)">
      <table class="table">
        <thead><tr><th>Team</th><th>Models</th><th>Members</th></tr></thead>
        <tbody id="teams-body"></tbody>
      </table>
    </div>

    <div class="card-header">
      <div class="section-label" style="margin:0">My Models</div>
      <a href="/app/models" class="link-action" style="font-size:var(--text-sm)">View all &rarr;</a>
    </div>
    <div class="table-wrap" style="margin-bottom:var(--space-6)">
      <table class="table">
        <thead><tr><th>Model</th><th>Team</th><th>Status</th><th></th></tr></thead>
        <tbody id="models-preview"></tbody>
      </table>
    </div>

    <div class="card-header">
      <div class="section-label" style="margin:0">My tickets</div>
      <a href="/app/tickets" class="link-action" style="font-size:var(--text-sm)">View all &rarr;</a>
    </div>
    <div class="metric-strip" id="ticket-metrics" style="margin-bottom:var(--space-3)"></div>
    <div class="table-wrap" style="margin-bottom:var(--space-4)">
      <table class="table">
        <thead><tr><th>Ticket</th><th>Filed</th><th>Severity</th><th>Status</th></tr></thead>
        <tbody id="recent-tickets-body"></tbody>
      </table>
    </div>
  </div>
</div>
<div id="loading-root" style="min-height:100vh;display:flex;align-items:center;justify-content:center;color:var(--text-muted);font-size:var(--text-sm)">Loading&hellip;</div>
"""

    script = """
<script>
  function greetingFor(user) {
    const h = new Date().getHours();
    const part = h < 12 ? 'Good morning' : h < 18 ? 'Good afternoon' : 'Good evening';
    return part + ', ' + (user.name || user.username);
  }

  // Plain-text strip, same shape as /admin's metric-strip - a value only
  // takes colour when it's itself the exception being reported (open
  // tickets), never as decoration.
  function stripItem(value, label, variant) {
    return '<div class="metric-strip-item"><div class="metric-strip-value' + (variant ? ' is-' + variant : '') + '">' + value + '</div><div class="metric-strip-label">' + label + '</div></div>';
  }

  async function loadOverview(user) {
    document.getElementById('greeting').textContent = greetingFor(user);

    let teams = [];
    try {
      teams = await Api.get('/users/me/teams');
      renderTeams(teams);
    } catch (e) {
      document.getElementById('teams-body').innerHTML = '<tr><td colspan="3">' + UI.errorState(e.message) + '</td></tr>';
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
      document.getElementById('recent-tickets-body').innerHTML = '<tr><td colspan="4">' + UI.errorState(e.message) + '</td></tr>';
    }
  }

  function renderTeams(teams) {
    const body = document.getElementById('teams-body');
    if (!teams.length) {
      body.innerHTML = '<tr><td colspan="3">' + UI.emptyState('No teams yet', 'Ask your admin to add you to a team.') + '</td></tr>';
      return;
    }
    body.innerHTML = teams.map(t =>
      '<tr class="is-interactive" data-team-id="' + t.id + '">' +
      '<td><div style="font-weight:var(--fw-semibold)">' + UI.escapeHtml(t.name) + '</div>' +
      (t.description ? '<div class="text-muted" style="font-size:var(--text-xs)">' + UI.escapeHtml(t.description) + '</div>' : '') + '</td>' +
      '<td class="text-secondary">' + t.model_count + '</td>' +
      '<td class="text-secondary">' + t.member_count + '</td>' +
      '</tr>'
    ).join('');
    body.querySelectorAll('[data-team-id]').forEach(row => {
      row.addEventListener('click', () => { location.href = '/app/teams/' + row.dataset.teamId; });
    });
  }

  function renderTicketMetrics(tickets) {
    const open = tickets.filter(t => t.status === 'open').length;
    const investigating = tickets.filter(t => t.status === 'investigating').length;
    const done = tickets.filter(t => t.status === 'resolved' || t.status === 'closed').length;
    document.getElementById('ticket-metrics').innerHTML =
      stripItem(open, 'Open', open > 0 ? 'warning' : undefined) +
      stripItem(investigating, 'Investigating') +
      stripItem(done, 'Resolved') +
      stripItem(tickets.length, 'Total filed');
  }

  function renderRecentTickets(tickets) {
    const body = document.getElementById('recent-tickets-body');
    if (!tickets.length) {
      body.innerHTML = '<tr><td colspan="4">' + UI.emptyState('No tickets yet', 'Filed an issue with a model? Track it here.') + '</td></tr>';
      return;
    }
    body.innerHTML = tickets.slice(0, 5).map(t =>
      '<tr><td style="max-width:220px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">' + UI.escapeHtml(t.title) + '</td>' +
      '<td class="text-muted">' + UI.timeAgo(t.filed_at) + '</td>' +
      '<td>' + UI.severityBadge(t.severity) + '</td>' +
      '<td>' + UI.statusBadge(t.status) + '</td>' +
      '</tr>'
    ).join('');
  }

  async function renderModelsPreview(teams) {
    const el = document.getElementById('models-preview');
    if (!teams.length) {
      el.innerHTML = '<tr><td colspan="4">' + UI.emptyState("Your team hasn't been granted model access yet.", "Contact your admin.") + '</td></tr>';
      return;
    }

    // Same source as /app/models: GET /teams/{id}/permissions across all
    // of the user's teams, deduped by deployment_id - not
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
      el.innerHTML = '<tr><td colspan="4">' + UI.emptyState("Your team hasn't been granted model access yet.", "Contact your admin.") + '</td></tr>';
      return;
    }
    el.innerHTML = rows.slice(0, 5).map(r =>
      '<tr><td class="mono">' + UI.escapeHtml(r.model_name) + '</td><td class="text-secondary">' + UI.escapeHtml(r.team_name) + '</td>' +
      '<td>' + UI.statusBadge(r.status) + '</td><td style="text-align:right">' +
      (r.can_predict ? '<a class="link-action" href="/app/teams/' + r.team_id + '">Get API key &rarr;</a>' : '<span class="text-muted" style="font-size:var(--text-xs)">View only</span>') +
      '</td></tr>'
    ).join('');
  }
</script>"""

    ready = "loadOverview(user);"

    html = (
        "<!DOCTYPE html>\n<html lang=\"en\">\n<head>\n<meta charset=\"UTF-8\">\n"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">\n"
        "<title>Overview - Vela</title>\n" + DS_ASSETS + "\n</head>\n<body>\n"
        + body
        + "\n" + _SCRIPTS + "\n" + script
        + _boot_script("/app", "", ready)
        + "\n</body>\n</html>"
    )
    return html


# =========================================================================
# Team detail - /app/teams/{team_id}
#
# One page serves every team_id - the id is read from the URL client-side
# and used to fetch GET /teams/{id} (name/description/workspace_id) and
# GET /teams/{id}/permissions (the model list, now enriched with
# task_type/status in services/teams.py). "Get API key" generates a key
# scoped to this exact team_id + deployment_id via
# POST /workspaces/{workspace_id}/api-keys - the workspace_id comes
# straight from GET /teams/{id}, so there's no ambiguity about which
# workspace a member's key should land in.
# =========================================================================

@router.get("/app/teams/{team_id}", response_class=HTMLResponse)
def member_team_detail_page(team_id: int):
    """De-duplicated as part of this DS migration: this used to embed a
    full Predictor.render/wire box plus its own "Get API key" flow per
    model, both of which now just duplicate the real per-model interface
    at /app/models/{deployment_id} (predict/explain) and the proper key
    picker at /app/api-keys. This page is a routing point into those now
    - each model row links straight to /app/models/{id} - not a second
    copy of either."""
    body = """
<div id="page-content" hidden>
  <div class="page-max">
    <a href="/app" class="link-secondary" style="font-size:var(--text-sm)">&larr; My Teams</a>
    <div class="page-header" style="margin-top:var(--space-3)">
      <div>
        <h1 class="page-title" id="team-name">Loading&hellip;</h1>
        <div class="page-description" id="team-description"></div>
      </div>
    </div>

    <div class="section-label" style="margin-top:0">Models</div>
    <div id="models-empty"></div>
    <div class="table-wrap" id="models-wrap" hidden>
      <table class="table">
        <thead><tr><th>Model</th><th>Task</th><th>Status</th><th></th></tr></thead>
        <tbody id="models-body"></tbody>
      </table>
    </div>
  </div>
</div>
<div id="loading-root" style="min-height:100vh;display:flex;align-items:center;justify-content:center;color:var(--text-muted);font-size:var(--text-sm)">Loading&hellip;</div>
"""

    script = """
<script>
  const TEAM_ID = location.pathname.split('/')[3];

  async function loadTeam() {
    try {
      const team = await Api.get('/teams/' + TEAM_ID);
      document.getElementById('team-name').textContent = team.name;
      document.getElementById('team-description').textContent = team.description || 'No description';
      document.title = team.name + ' - Vela';
      const crumb = document.querySelector('.shell-breadcrumb-current');
      if (crumb) crumb.textContent = team.name;
      renderModels(team.permissions || []);
    } catch (e) {
      document.getElementById('models-wrap').hidden = true;
      document.getElementById('models-empty').innerHTML = UI.errorState(e.message, loadTeam);
    }
  }

  // Admin "Disable" (/admin/models) hides a model from members entirely
  // rather than showing it greyed out - the admin teams-page
  // (/admin/teams-page) shows these same permission rows unfiltered,
  // since an admin still needs to see/manage a disabled model's grants.
  function renderModels(perms) {
    perms = perms.filter(p => p.is_active !== false);
    const wrap = document.getElementById('models-wrap');
    const empty = document.getElementById('models-empty');
    if (!perms.length) {
      wrap.hidden = true;
      empty.innerHTML = UI.emptyState('No models yet', 'This team has not been granted access to any models.');
      return;
    }
    empty.innerHTML = '';
    wrap.hidden = false;

    const body = document.getElementById('models-body');
    body.innerHTML = perms.map(p => {
      const href = '/app/models/' + p.deployment_id;
      return '<tr class="is-interactive" data-model-href="' + href + '">' +
        '<td><a href="' + href + '" class="mono">' + UI.escapeHtml(p.model_name) + '</a></td>' +
        '<td class="text-secondary">' + UI.escapeHtml(p.task_type) + '</td>' +
        '<td>' + UI.statusBadge(p.status) + '</td>' +
        '<td>' + (p.can_predict ? '' : UI.badge('View only', 'neutral')) + '</td>' +
        '</tr>';
    }).join('');
    // Whole row navigates (matches the Overview page's My Teams table),
    // but a click on the model's own link is left alone so ctrl/cmd-click
    // and right-click-to-open-in-new-tab still work as a real link.
    body.querySelectorAll('[data-model-href]').forEach(row => {
      row.addEventListener('click', (e) => {
        if (e.target.closest('a')) return;
        location.href = row.dataset.modelHref;
      });
    });
  }
</script>"""

    ready = "loadTeam();"

    html = (
        "<!DOCTYPE html>\n<html lang=\"en\">\n<head>\n<meta charset=\"UTF-8\">\n"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">\n"
        "<title>Team - Vela</title>\n" + DS_ASSETS + "\n</head>\n<body>\n"
        + body
        + "\n" + _SCRIPTS + "\n" + script
        + _boot_script("/app/teams/" + str(team_id), "Team", ready)
        + "\n</body>\n</html>"
    )
    return html


# =========================================================================
# Models - /app/models
# =========================================================================

@router.get("/app/models", response_class=HTMLResponse)
def member_models_page():
    """No model selected yet - model selection itself now lives in the
    sidebar's "My Models" dropdown (Shell, static/js/shell.js), not on this
    page. This route just resolves whether the user has any access at all,
    so it can point them at the sidebar (or at their admin, if there's
    nothing to point at). Picking a model navigates to
    /app/models/{deployment_id} below, which renders the actual detail/
    tester interface Part 3 built - unchanged, just no longer reached via
    an in-page list."""
    body = """
<div id="page-content" hidden>
  <div class="page-max">
    <div class="page-header">
      <div>
        <h1 class="page-title">My Models</h1>
        <div class="page-description">Models your teams have been granted access to.</div>
      </div>
    </div>
    <div id="models-empty"></div>
  </div>
</div>
<div id="loading-root" style="min-height:100vh;display:flex;align-items:center;justify-content:center;color:var(--text-muted);font-size:var(--text-sm)">Loading&hellip;</div>
"""

    script = """
<script>
  async function loadModels() {
    const empty = document.getElementById('models-empty');
    empty.innerHTML = '';
    try {
      const rows = await Shell.fetchMemberModelRows();
      empty.innerHTML = rows.length
        ? UI.emptyState('Select a model', 'Pick a model from "My Models" in the sidebar to try it and see how it performs.')
        : UI.emptyState("Your team hasn't been granted model access yet.", "Contact your admin.");
    } catch (e) {
      empty.innerHTML = UI.errorState(e.message, loadModels);
    }
  }
</script>"""

    ready = "loadModels();"

    html = (
        "<!DOCTYPE html>\n<html lang=\"en\">\n<head>\n<meta charset=\"UTF-8\">\n"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">\n"
        "<title>Models - Vela</title>\n" + DS_ASSETS + "\n</head>\n<body>\n"
        + body
        + "\n" + _SCRIPTS + "\n" + script
        + _boot_script("/app/models", "My Models", ready)
        + "\n</body>\n</html>"
    )
    return html


@router.get("/app/models/{deployment_id}", response_class=HTMLResponse)
def member_model_detail_page(deployment_id: int):
    """The actual per-model tester (input-by-type, predict, explain) - same
    markup/logic member_models_page used to render into #model-detail once
    a row was picked from its in-page list, just addressed by its own URL
    now that the picking happens in the sidebar (see shell.js's "My
    Models" dropdown, which links straight here per model)."""
    body = """
<div id="page-content" hidden>
  <div class="page-max">
    <a href="/app/models" class="link-secondary" style="font-size:var(--text-sm)">&larr; My Models</a>
    <div id="model-detail" style="margin-top:var(--space-4)"></div>
  </div>
</div>
<div id="loading-root" style="min-height:100vh;display:flex;align-items:center;justify-content:center;color:var(--text-muted);font-size:var(--text-sm)">Loading&hellip;</div>
"""

    script = """
<script>
  const DEPLOYMENT_ID = parseInt(location.pathname.split('/')[3], 10);

  async function loadModel() {
    const detail = document.getElementById('model-detail');
    try {
      const rows = await Shell.fetchMemberModelRows();
      const r = rows.find(row => row.deployment_id === DEPLOYMENT_ID);
      if (!r) {
        detail.innerHTML = UI.emptyState(
          'Model not found',
          "This model doesn't exist, or your team hasn't been granted access to it."
        );
        return;
      }
      document.title = r.model_name + ' - Vela';
      const crumb = document.querySelector('.shell-breadcrumb-current');
      if (crumb) crumb.textContent = r.model_name;
      renderDetail(r);
    } catch (e) {
      detail.innerHTML = UI.errorState(e.message, loadModel);
    }
  }

  function renderDetail(r) {
    const detail = document.getElementById('model-detail');
    const uid = 'd' + r.deployment_id;
    const testerHtml = r.can_predict
      ? Predictor.render(uid, r.team_id, r.deployment_id, r.input_type, r.input_schema, r.task_type)
      : UI.badge('View only', 'neutral');

    detail.innerHTML =
      '<div class="card-header">' +
      '<div><div class="card-title">' + UI.escapeHtml(r.model_name) + '</div>' +
      '<div class="card-subtitle">' + UI.escapeHtml(r.task_type) + ' &middot; ' + UI.escapeHtml(r.team_name) + '</div></div>' +
      UI.statusBadge(r.status) +
      '</div>' +
      '<div style="margin-bottom:var(--space-4)"><a class="link-action" style="font-size:var(--text-xs)" href="/app/tickets?model=' + encodeURIComponent(r.model_name) + '">Report an issue &rarr;</a></div>' +
      testerHtml;

    if (r.can_predict) {
      Predictor.wire(uid, r.team_id, r.deployment_id, r.input_type, r.input_schema, r.task_type);
    }
  }
</script>"""

    ready = "loadModel();"

    html = (
        "<!DOCTYPE html>\n<html lang=\"en\">\n<head>\n<meta charset=\"UTF-8\">\n"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">\n"
        "<title>Model - Vela</title>\n" + DS_ASSETS + "\n</head>\n<body>\n"
        + body
        + "\n" + _SCRIPTS + "\n" + script
        + _boot_script("/app/models/" + str(deployment_id), "My Models", ready)
        + "\n</body>\n</html>"
    )
    return html


# =========================================================================
# Tickets - /app/tickets
# =========================================================================

@router.get("/app/tickets", response_class=HTMLResponse)
def member_tickets_page():
    """Doesn't share a body/script with /admin/tickets-page (admin_pages.py)
    - that screen is every team's tickets behind a filter toolbar with
    status editing; this one is GET /tickets/my (this member's own tickets
    only, no filters - there just isn't enough volume to need them) plus
    the one thing admin doesn't have, filing a new one. So it's styled to
    match admin's DS look (page-header, table, the same louder severity-
    as-primary-signal dot below) without pulling in a shared fragment.

    grid-split's 340px/1fr split is used the "right" way round here - the
    filing form (a handful of stacked fields) is genuinely narrow-shaped
    and gets the 340px column; the ticket table gets the wide 1fr column
    it actually needs. (The pre-DS version of this page had that
    backwards - the table squeezed into 340px - fixed as part of this
    rebuild.)"""
    body = """
<div id="page-content" hidden>
  <div class="page-max">
    <div class="page-header">
      <div>
        <h1 class="page-title">Tickets</h1>
        <div class="page-description">Issues and feedback you've filed on models your teams use.</div>
      </div>
      <div class="page-actions">
        <button class="btn btn-secondary btn-sm" id="refresh-btn" type="button">Refresh</button>
      </div>
    </div>

    <div class="grid-split">
      <div>
        <div class="section-label" style="margin-top:0">New ticket</div>
        <form id="new-ticket-form" novalidate>
          <div class="field"><label class="field-label" for="nt-title">Title</label><input class="input" id="nt-title" required></div>
          <div class="field"><label class="field-label" for="nt-desc">Description</label><textarea class="textarea" id="nt-desc" rows="3" required></textarea></div>
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
          <div class="field"><label class="field-label" for="nt-evidence">Evidence <span class="field-optional">optional</span></label><textarea class="textarea" id="nt-evidence" rows="2" placeholder="Logs, example inputs, screenshots described…"></textarea></div>
          <div class="field-error" id="nt-error" role="alert"></div>
          <button class="btn btn-primary btn-block" type="submit" id="nt-submit">File ticket</button>
        </form>
      </div>

      <div>
        <div class="section-label" style="margin-top:0">Filed tickets</div>
        <div class="table-wrap">
          <table class="table">
            <thead>
              <tr><th>Title</th><th>Severity</th><th>Status</th><th>Filed</th></tr>
            </thead>
            <tbody id="tickets-body"></tbody>
          </table>
        </div>
      </div>
    </div>
  </div>
</div>
<div id="loading-root" style="min-height:100vh;display:flex;align-items:center;justify-content:center;color:var(--text-muted);font-size:var(--text-sm)">Loading&hellip;</div>
"""

    script = """
<script>
  // Same local override admin_tickets_page (admin_pages.py) uses instead
  // of the shared UI.severityBadge - severity is this screen's primary
  // signal (critical/high colored, medium/low neutral), louder than the
  // shared helper's medium=blue default. Status stays on the plain
  // UI.statusBadge. Duplicated rather than shared since the two pages
  // don't share a body (see the route's own docstring above).
  const TICKET_SEVERITY_VARIANT = { critical: 'error', high: 'warning', medium: 'neutral', low: 'neutral' };
  function ticketSeverityDot(sev) {
    const s = String(sev || 'medium').toLowerCase();
    return UI.statusDot(s.charAt(0).toUpperCase() + s.slice(1), TICKET_SEVERITY_VARIANT[s] || 'neutral');
  }

  let myTickets = [];

  async function loadTickets() {
    const body = document.getElementById('tickets-body');
    body.innerHTML = UI.skeletonRows(4, 4);
    try {
      myTickets = await Api.get('/tickets/my');
      renderTickets();
    } catch (e) {
      body.innerHTML = '<tr><td colspan="4">' + UI.errorState(e.message, loadTickets) + '</td></tr>';
    }
  }

  function renderTickets() {
    const body = document.getElementById('tickets-body');
    if (!myTickets.length) {
      body.innerHTML = '<tr><td colspan="4">' + UI.emptyState('No tickets filed yet', 'Run into a problem with a model? File a ticket and track it here.') + '</td></tr>';
      return;
    }
    body.innerHTML = myTickets.map(t =>
      '<tr class="is-interactive" data-open-ticket="' + t.id + '">' +
      '<td style="max-width:220px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">' + UI.escapeHtml(t.title) + '</td>' +
      '<td>' + ticketSeverityDot(t.severity) + '</td>' +
      '<td>' + UI.statusBadge(t.status) + '</td>' +
      '<td class="text-secondary">' + UI.timeAgo(t.filed_at) + '</td>' +
      '</tr>'
    ).join('');
    body.querySelectorAll('[data-open-ticket]').forEach(row => {
      row.addEventListener('click', () => viewTicket(row.dataset.openTicket));
    });
  }

  // Read-only - unlike admin's version of this modal, there's no status/
  // resolution-note editing here, a member can only file and track.
  function viewTicket(id) {
    const t = myTickets.find(x => String(x.id) === String(id));
    if (!t) return;
    const overlay = UI.openModal({
      title: t.title,
      bodyHtml: `
        <div style="margin-bottom:.75rem;display:flex;gap:.5rem;flex-wrap:wrap;align-items:center">${ticketSeverityDot(t.severity)}${UI.statusBadge(t.status)}${UI.badge(t.ticket_type, 'neutral')}</div>
        <div class="text-secondary" style="font-size:var(--text-sm);white-space:pre-wrap;margin-bottom:.75rem">${UI.escapeHtml(t.description)}</div>
        ${t.evidence ? '<div class="section-label">Evidence</div><div class="text-secondary" style="font-size:var(--text-xs);white-space:pre-wrap;margin-bottom:.75rem">' + UI.escapeHtml(t.evidence) + '</div>' : ''}
        <div class="text-muted" style="font-size:var(--text-xs);margin-bottom:.75rem">Filed ${UI.fmtDate(t.filed_at)}</div>
        ${t.resolution_note ? '<div class="alert alert-info"><div><div class="alert-title">Resolution</div><div class="alert-body">' + UI.escapeHtml(t.resolution_note) + '</div></div></div>' : ''}
      `,
      footerHtml: `<button class="btn btn-secondary" id="tk-close" type="button">Close</button>`,
    });
    overlay.querySelector('#tk-close').addEventListener('click', UI.closeModal);
  }

  // Inline form (spec: its own column, no card/modal) - deep link from a
  // model card (/app/tickets?model=NAME) pre-fills the description
  // instead of opening anything.
  const params = new URLSearchParams(location.search);
  const modelParam = params.get('model');
  if (modelParam) {
    document.getElementById('nt-desc').value = 'Regarding model: ' + modelParam + '\\n\\n';
  }

  document.getElementById('refresh-btn').addEventListener('click', () => loadTickets());

  document.getElementById('new-ticket-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    const errorEl = document.getElementById('nt-error');
    const submitBtn = document.getElementById('nt-submit');
    const title = document.getElementById('nt-title').value.trim();
    const description = document.getElementById('nt-desc').value.trim();
    const ticket_type = document.getElementById('nt-type').value;
    const severity = document.getElementById('nt-severity').value;
    const evidence = document.getElementById('nt-evidence').value.trim();
    errorEl.textContent = '';
    if (!title || !description) {
      errorEl.textContent = 'Title and description are required.';
      return;
    }
    submitBtn.disabled = true;
    try {
      await Api.post('/tickets', { title, description, ticket_type, severity, evidence });
      UI.toast('Ticket filed', 'success');
      document.getElementById('new-ticket-form').reset();
      loadTickets();
    } catch (err) {
      errorEl.textContent = err.message || 'Could not file ticket.';
    } finally {
      submitBtn.disabled = false;
    }
  });
</script>"""

    ready = "loadTickets();"

    html = (
        "<!DOCTYPE html>\n<html lang=\"en\">\n<head>\n<meta charset=\"UTF-8\">\n"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">\n"
        "<title>Tickets - Vela</title>\n" + DS_ASSETS + "\n</head>\n<body>\n"
        + body
        + "\n" + _SCRIPTS + "\n" + script
        + _boot_script("/app/tickets", "Tickets", ready)
        + "\n</body>\n</html>"
    )
    return html


# =========================================================================
# API Keys - /app/api-keys
# =========================================================================

@router.get("/app/api-keys", response_class=HTMLResponse)
def member_api_keys_page():
    """Doesn't share a body/script with /admin/api-keys (admin_pages.py) -
    that screen lists every workspace an admin belongs to with a filter
    toolbar; a member only ever sees workspaces they're already in via a
    team, and there's no cross-workspace volume here to need filtering.
    Styled to match admin's DS look (page-header, table, slide-over,
    modal) without pulling in a shared fragment - same call this codebase
    already made for member Tickets vs admin Tickets.

    Unlike before this rebuild, this page now also CREATES keys (admin's
    page always could) - previously that only happened from a team's own
    page (/app/teams/{team_id}'s "Get API key" button, untouched, still
    works). POST /workspaces/{id}/api-keys itself doesn't check that
    team_id/deployment_id actually belong to the caller - the scoping is
    purely which options this page ever offers, so the picker below is
    built ONLY from GET /users/me/teams + GET /teams/{id}/permissions
    (the same calls the sidebar's My Models dropdown and the team page
    already use) - never a free-typed id - so this can't create a key
    wider than a member could already get from the team page."""
    body = """
<div id="page-content" hidden>
  <div class="page-max">
    <div class="page-header">
      <div>
        <h1 class="page-title">API Keys</h1>
        <div class="page-description">Keys for calling models your teams have access to. Each key is scoped to one team's grant on one model.</div>
      </div>
      <div class="page-actions">
        <button class="btn btn-secondary btn-sm" id="refresh-btn" type="button">Refresh</button>
        <button class="btn btn-primary btn-sm" id="new-key-btn" type="button">New key</button>
      </div>
    </div>

    <div class="table-wrap">
      <table class="table" style="min-width:640px">
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
  // A member can belong to more than one workspace (one per team), so
  // keys are fetched per-workspace and merged; keyWorkspaceMap remembers
  // which workspace each key came from, since revoke needs that id.
  let cachedRows = [];
  let keyWorkspaceMap = {};

  function initApiKeys() {
    document.getElementById('refresh-btn').addEventListener('click', () => loadKeys());
    wireNewKeyPanel();
    loadKeys();
    ensureModelsLoaded(); // starts the picker fetch now, not on first open
  }

  async function loadKeys() {
    const body = document.getElementById('keys-body');
    body.innerHTML = UI.skeletonRows(4, 6);
    try {
      const workspaces = await Api.get('/workspaces');
      if (!workspaces.length) {
        cachedRows = [];
        keyWorkspaceMap = {};
        body.innerHTML = '<tr><td colspan="6">' + UI.emptyState('No workspace access yet', 'Ask your admin to provision access.') + '</td></tr>';
        return;
      }
      keyWorkspaceMap = {};
      const perWorkspace = await Promise.allSettled(workspaces.map(ws => Api.get('/workspaces/' + ws.id + '/api-keys')));
      const rows = [];
      perWorkspace.forEach((r, i) => {
        if (r.status !== 'fulfilled') return;
        r.value.forEach(k => {
          keyWorkspaceMap[k.id] = workspaces[i].id;
          rows.push(k);
        });
      });
      cachedRows = rows;
      renderKeysTable();
    } catch (e) {
      cachedRows = [];
      body.innerHTML = '<tr><td colspan="6">' + UI.errorState(e.message, loadKeys) + '</td></tr>';
    }
  }

  function renderKeysTable() {
    const body = document.getElementById('keys-body');
    if (!cachedRows.length) {
      body.innerHTML = '<tr><td colspan="6">' + UI.emptyState('No API keys yet', 'Generate one with the button above.') + '</td></tr>';
      return;
    }
    body.innerHTML = cachedRows.map(renderKeyRow).join('');
    body.querySelectorAll('[data-revoke-key]').forEach(btn => {
      btn.addEventListener('click', () => confirmRevokeKey(btn.dataset.revokeKey, btn.dataset.name));
    });
  }

  // Team + Model badges, not the raw workspace name - a member doesn't
  // navigate by workspace the way an admin comparing workspaces does,
  // and in practice every member key is team/model-scoped (see the
  // route's own docstring); a key with neither is called out plainly
  // rather than silently rendering blank.
  function scopeHtml(k) {
    const parts = [];
    if (k.team_name) parts.push(UI.badge('Team: ' + k.team_name, 'neutral'));
    if (k.model_name || k.deployment_name) parts.push(UI.badge('Model: ' + (k.model_name || k.deployment_name), 'neutral'));
    return parts.length ? parts.join(' ') : '<span class="text-muted" style="font-size:var(--text-xs)">Unscoped</span>';
  }

  // Never the full key - only ever the prefix this list endpoint
  // returns, masked with an ellipsis (same as admin's version).
  function renderKeyRow(k) {
    return '<tr>' +
      '<td>' + UI.escapeHtml(k.name || 'Unnamed key') + '</td>' +
      '<td class="mono">' + UI.escapeHtml(k.prefix) + '&hellip;</td>' +
      '<td>' + scopeHtml(k) + '</td>' +
      '<td class="text-secondary">' + UI.fmtDate(k.created_at) + '</td>' +
      '<td class="text-secondary">' + (k.last_used_at ? UI.timeAgo(k.last_used_at) : 'Never') + '</td>' +
      '<td class="num"><button class="link-action link-danger" data-revoke-key="' + k.id + '" data-name="' + UI.escapeHtml(k.name || '') + '" type="button">Revoke</button></td>' +
      '</tr>';
  }

  // Irreversible - there is no un-revoke endpoint, and anything using
  // the key breaks immediately - same type-to-confirm discipline as
  // admin's version of this modal, not a lightweight Cancel/Confirm.
  function confirmRevokeKey(keyId, name) {
    const wsId = keyWorkspaceMap[keyId];
    const overlay = UI.openModal({
      title: 'Revoke ' + (name || 'this key'),
      bodyHtml: `
        <div class="alert alert-danger" style="margin-bottom:var(--space-3)">
          <div><div class="alert-title">This cannot be undone</div><div>Anything using this key will stop working immediately. Type the key name to confirm.</div></div>
        </div>
        <div class="field">
          <label class="field-label" for="revoke-key-confirm-name">Key name</label>
          <input class="input" id="revoke-key-confirm-name" placeholder="${UI.escapeHtml(name || '')}">
        </div>
        <div class="field-error" id="revoke-key-confirm-error" role="alert"></div>
      `,
      footerHtml: `<button class="btn btn-ghost" id="revoke-key-cancel" type="button">Cancel</button>
                   <button class="btn btn-danger" id="revoke-key-confirm" type="button" disabled>Revoke</button>`,
    });
    const input = overlay.querySelector('#revoke-key-confirm-name');
    const confirmBtn = overlay.querySelector('#revoke-key-confirm');
    const errorEl = overlay.querySelector('#revoke-key-confirm-error');
    input.addEventListener('input', () => { confirmBtn.disabled = input.value !== (name || ''); });
    overlay.querySelector('#revoke-key-cancel').addEventListener('click', UI.closeModal);
    confirmBtn.addEventListener('click', async () => {
      confirmBtn.disabled = true;
      confirmBtn.textContent = 'Revoking…';
      errorEl.textContent = '';
      try {
        await Api.del('/workspaces/' + wsId + '/api-keys/' + keyId);
        UI.closeModal();
        UI.toast('Key revoked', 'success');
        loadKeys();
      } catch (e) {
        errorEl.textContent = e.message || 'Could not revoke key.';
        confirmBtn.disabled = false;
        confirmBtn.textContent = 'Revoke';
      }
    });
  }

  // ================================================================
  // New key slide-over. The picker is every (team, predict-capable
  // model) pair this member's teams have been granted - built from
  // GET /users/me/teams -> GET /teams/{id}/permissions, the same calls
  // the sidebar's My Models dropdown and the team page use, and NOT
  // deduped by deployment_id the way that dropdown is: the same model
  // granted via two different teams is two separate options here,
  // since the team is what the created key gets scoped to (see the
  // route's own docstring for why this can't widen what a member could
  // already do from the team page).
  //
  // The form and the one-time reveal are two states of the SAME panel
  // (renderNewKeyForm() / renderKeyReveal() swap #new-key-body's
  // content in place), same pattern as admin_api_keys_page - one
  // surface, and the reveal can't be reached without just having gone
  // through the form.
  // ================================================================

  let cachedModels = [];
  let modelsLoadPromise = null;

  function ensureModelsLoaded() {
    if (!modelsLoadPromise) modelsLoadPromise = loadCreatableModels();
    return modelsLoadPromise;
  }

  async function loadCreatableModels() {
    try {
      const teams = await Api.get('/users/me/teams');
      const perTeam = await Promise.allSettled(
        teams.map(t => Api.get('/teams/' + t.id + '/permissions').then(perms =>
          perms
            .filter(p => p.is_active !== false && p.can_predict)
            .map(p => ({
              team_id: t.id, team_name: t.name, workspace_id: t.workspace_id,
              deployment_id: p.deployment_id, model_name: p.model_name,
            }))
        ))
      );
      const models = [];
      perTeam.forEach(r => { if (r.status === 'fulfilled') models.push(...r.value); });
      cachedModels = models;
    } catch (e) {
      cachedModels = [];
    }
  }

  function renderNewKeyForm() {
    const body = document.getElementById('new-key-body');
    if (!cachedModels.length) {
      body.innerHTML = UI.emptyState(
        'No models to scope a key to',
        "None of your teams have a predictable model yet - ask your admin for access."
      );
      return;
    }

    const options = cachedModels.map((m, i) =>
      '<option value="' + i + '">' + UI.escapeHtml(m.model_name) + ' &mdash; ' + UI.escapeHtml(m.team_name) + '</option>'
    ).join('');

    body.innerHTML = `
      <form class="form" id="new-key-form" novalidate>
        <div class="field">
          <label class="field-label" for="nk-model">Model</label>
          <select class="select" id="nk-model">${options}</select>
        </div>
        <div class="field"><label class="field-label" for="nk-name">Key name</label><input class="input" id="nk-name" required></div>
        <div class="field-error" id="nk-error" role="alert"></div>
        <button class="btn btn-primary btn-block" type="submit" id="nk-submit">Generate key</button>
      </form>`;

    const modelSel = document.getElementById('nk-model');
    const nameInput = document.getElementById('nk-name');
    // Auto-suggests a name from the picked model, but never clobbers
    // something the member already typed - only refills while the field
    // is empty or still holds the last suggestion.
    let lastAutoName = '';
    function fillDefaultName() {
      const m = cachedModels[parseInt(modelSel.value, 10)];
      if (!m) return;
      const suggested = m.team_name + ': ' + m.model_name;
      if (!nameInput.value || nameInput.value === lastAutoName) {
        nameInput.value = suggested;
        lastAutoName = suggested;
      }
    }
    modelSel.addEventListener('change', fillDefaultName);
    fillDefaultName();

    document.getElementById('new-key-form').addEventListener('submit', async (e) => {
      e.preventDefault();
      const errorEl = document.getElementById('nk-error');
      const submitBtn = document.getElementById('nk-submit');
      const m = cachedModels[parseInt(modelSel.value, 10)];
      const name = nameInput.value.trim();
      if (!name) { errorEl.textContent = 'Give the key a name.'; return; }
      if (!m) { errorEl.textContent = 'Pick a model.'; return; }
      submitBtn.disabled = true;
      submitBtn.textContent = 'Generating…';
      errorEl.textContent = '';
      try {
        const result = await Api.post('/workspaces/' + m.workspace_id + '/api-keys', {
          name, team_id: m.team_id, deployment_id: m.deployment_id,
        });
        renderKeyReveal(result);
        loadKeys();
      } catch (err) {
        errorEl.textContent = err.message || 'Could not create key.';
        submitBtn.disabled = false;
        submitBtn.textContent = 'Generate key';
      }
    });
  }

  // The key in result.key is the only time it's ever available. Copy
  // uses UI.copyText's clipboard-with-execCommand-fallback (this backend
  // is commonly served over plain HTTP, where navigator.clipboard is
  // just undefined) and always shows whether it actually worked, never a
  // silent no-op.
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

  // Opens immediately (no wait for the picker fetch, which was already
  // kicked off at page load by initApiKeys) with a tiny loading state,
  // then swaps in the real form once loadCreatableModels resolves - so a
  // click right after page load can't race an empty cachedModels into
  // wrongly showing "no models" (see the shared ensureModelsLoaded).
  async function openNewKeyPanel() {
    const titleEl = document.getElementById('new-key-panel-title');
    if (titleEl) titleEl.textContent = 'New key';
    document.getElementById('new-key-body').innerHTML = '<span class="skeleton skeleton-text" style="display:block;max-width:180px">&nbsp;</span>';
    openSlideover('new-key-panel', null, closeNewKeyPanel);
    await ensureModelsLoaded();
    renderNewKeyForm();
    const modelSel = document.getElementById('nk-model');
    if (modelSel) modelSel.focus();
  }

  function closeNewKeyPanel() {
    closeSlideoverChrome('new-key-panel');
  }

  function wireNewKeyPanel() {
    const panel = document.getElementById('new-key-panel');
    document.getElementById('new-key-btn').addEventListener('click', openNewKeyPanel);
    document.getElementById('close-new-key-panel').addEventListener('click', closeNewKeyPanel);
    panel.addEventListener('click', (e) => { if (e.target === panel) closeNewKeyPanel(); });
  }

  // ================================================================
  // Shared slide-over chrome (open/close/focus-trap) - duplicated from
  // admin_api_keys_page (admin_pages.py) rather than factored out,
  // matching that page's own note: each route's <script> is self-
  // contained, no shared ds.js module yet.
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
        "<title>API Keys - Vela</title>\n" + DS_ASSETS + "\n</head>\n<body>\n"
        + body
        + "\n" + _SCRIPTS + "\n" + script
        + _boot_script("/app/api-keys", "API Keys", ready)
        + "\n</body>\n</html>"
    )
    return html


# =========================================================================
# Monitoring - /app/monitoring
# =========================================================================

@router.get("/app/monitoring", response_class=HTMLResponse)
def member_monitoring_page():
    ready = "Monitoring.start({role: 'member'});"

    html = (
        "<!DOCTYPE html>\n<html lang=\"en\">\n<head>\n<meta charset=\"UTF-8\">\n"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">\n"
        "<title>Model Health - Vela</title>\n" + DS_ASSETS + "\n" + CHART_JS_CDN + "\n" + MONITORING_CSS + "\n</head>\n<body>\n"
        + MONITORING_BODY
        + "\n" + _SCRIPTS + "\n" + MONITORING_SCRIPTS_EXTRA
        + _boot_script("/app/monitoring", "Monitoring", ready)
        + "\n</body>\n</html>"
    )
    return html


# =========================================================================
# Drift - folded into /app/monitoring's #drift-section (see
# _page_fragments.py). This route is kept only as a redirect so old links
# and bookmarks to the former standalone Drift page don't 404.
# =========================================================================

@router.get("/app/drift")
def member_drift_page():
    return RedirectResponse(url="/app/monitoring#drift-section", status_code=302)


# =========================================================================
# Documentation - /app/docs
# =========================================================================

@router.get("/app/docs", response_class=HTMLResponse)
def member_docs_page():
    """Own inline DS body rather than the shared DOCS_BODY in
    _page_fragments.py - same call admin_docs_page already made: that
    constant is legacy/_ASSETS-era, and editing it would mean touching a
    file this migration isn't scoped to. Same element ids as admin's
    version (docs-subtitle, docs-model-select, card-result), so the
    shared docs.js (DOCS_SCRIPTS_EXTRA, unchanged) keeps driving it
    unmodified - docs.js already branches on role itself (which model-
    list endpoint it reads, whether an edit form appears under
    card-result), so member stays read-appropriate with no page-level
    change needed. DOCS_BODY itself is left alone in _page_fragments.py;
    it's now unused (admin moved off it first, this was its last caller)
    but that's not this page's file to clean up."""
    body = """
<div id="page-content" hidden>
  <div class="page-narrow">
    <div class="page-header">
      <div>
        <h1 class="page-title">Documentation</h1>
        <div class="page-description" id="docs-subtitle">Select a model to view its documentation.</div>
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

    ready = "Docs.start({role: 'member'});"

    html = (
        "<!DOCTYPE html>\n<html lang=\"en\">\n<head>\n<meta charset=\"UTF-8\">\n"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">\n"
        "<title>Documentation - Vela</title>\n" + DS_ASSETS + "\n</head>\n<body>\n"
        + body
        + "\n" + _SCRIPTS + "\n" + DOCS_SCRIPTS_EXTRA
        + _boot_script("/app/docs", "Documentation", ready)
        + "\n</body>\n</html>"
    )
    return html


# =========================================================================
# Settings - /app/settings
# =========================================================================

@router.get("/app/settings", response_class=HTMLResponse)
def member_settings_page():
    """Own inline DS body rather than the shared SETTINGS_BODY in
    _page_fragments.py - same call admin_settings_page already made (see
    its comment): that constant is legacy/_ASSETS-era, and editing it
    would mean touching a file this migration isn't scoped to. Same
    account-card + change-password element ids as admin's version
    (acc-username/acc-name/acc-role, pw-form + its fields/error/submit),
    so the shared settings.js (SETTINGS_SCRIPTS_EXTRA, unchanged) keeps
    driving it unmodified. No "AI provider" section - that's admin-only.
    SETTINGS_BODY itself is left alone in _page_fragments.py; it's now
    unused (admin moved off it first, this was its last caller) but
    that's not this page's file to clean up."""
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
        "<title>Settings - Vela</title>\n" + DS_ASSETS + "\n</head>\n<body>\n"
        + body
        + "\n" + _SCRIPTS + "\n" + SETTINGS_SCRIPTS_EXTRA
        + _boot_script("/app/settings", "Settings", ready)
        + "\n</body>\n</html>"
    )
    return html
