"""
Shared HTML fragments used by more than one page router (admin_pages.py,
member_pages.py).

Model Health used to be two pages (Model Health + a separate Drift page)
that opened on the same model picker and answered the same underlying
question ("how is this model doing?") - Drift was even just a teaser link
away from Model Health. They're merged into one screen now: pick a model
once, see health + performance + drift together, model-centric (spec
redesign), never a platform-wide rollup. /admin/drift and /app/drift are
now redirects into this screen's #drift-section (see admin_pages.py /
member_pages.py). Node CPU/memory and the services list are deliberately
NOT here - that's system/infrastructure monitoring, and it already has a
real home at /admin/infrastructure (admin-only). See monitoring.js for
what's real vs. honestly marked "not instrumented" - only one Prometheus
job exists in this backend today (services/timeline.py's DEFAULT_JOB).
"""

CHART_JS_CDN = '<script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.min.js"></script>'

# Cache-busting query param on our own monitoring/drift static assets only
# (third-party CDN URLs above are already version-pinned in their path).
# These files are served from a fixed URL with no content hash, so a
# browser or intermediate proxy that cached the pre-redesign monitoring.js
# against that same URL would keep serving it after a redeploy - same
# HTML (fresh, since FastAPI never caches it), stale JS silently doing
# nothing with the new page's element ids. Bump this string on every
# change to these files.
_STATIC_V = "12"
MONITORING_CSS = f'<link rel="stylesheet" href="/static/css/monitoring.css?v={_STATIC_V}">'
MODEL_CATALOG_JS = f'<script src="/static/js/models.js?v={_STATIC_V}"></script>'

# ds/* bundle for the two Model Health routes (admin + member) - the only
# screens migrated to the design system so far that are shared code rather
# than a single self-contained admin page, so this lives here once instead
# of being redefined per router. /admin/drift and /app/drift are plain
# redirects (see admin_pages.py / member_pages.py) and never render this
# bundle themselves. Every other admin/member page still loads the legacy
# _ASSETS.
DS_ASSETS = (
    '<link rel="stylesheet" href="/static/css/ds/tokens.css?v=ds5">\n'
    '<link rel="stylesheet" href="/static/css/ds/base.css?v=ds5">\n'
    '<link rel="stylesheet" href="/static/css/ds/primitives.css?v=ds5">\n'
    '<link rel="stylesheet" href="/static/css/ds/shell.css?v=ds7">'
)

MONITORING_BODY = """
<div id="page-content" hidden>
  <div class="page-max">
    <div class="page-header">
      <div>
        <h1 class="page-title">Model Health</h1>
      </div>
    </div>

    <div class="panel" style="display:flex;align-items:center;gap:var(--space-4);flex-wrap:wrap;padding:var(--space-3) var(--space-4);margin-bottom:var(--space-3)">
      <div id="model-picker"></div>
      <div id="model-identity" style="display:flex;align-items:center;gap:var(--space-2);flex:1;min-width:0;padding-left:var(--space-4);border-left:var(--border-width) solid var(--border-subtle)">
        <span class="card-title" id="mh-name" style="overflow:hidden;text-overflow:ellipsis;white-space:nowrap">&mdash;</span>
        <span id="mh-status-badge"></span>
        <span class="text-muted" id="mh-task" style="font-size:var(--text-xs);white-space:nowrap"></span>
      </div>
    </div>

    <div id="model-empty"></div>

    <div id="model-content" hidden>
      <div class="metric-strip" id="mh-status-stats" style="margin-bottom:var(--space-2)">
        <span id="mh-health-stats" style="display:contents"></span>
        <div class="metric-strip-item"><div class="metric-strip-value" id="mh-drift-value">&mdash;</div><div class="metric-strip-label">Drift</div></div>
      </div>
      <div style="margin-bottom:var(--space-3)">
        <a class="link-action" style="font-size:var(--text-xs)" href="#drift-section">Full drift analysis &darr;</a>
      </div>

      <div id="mh-performance"></div>

      <div id="drift-section" style="margin-top:var(--space-4)">
        <div class="section-label" style="margin-top:0">Drift</div>

        <div id="d-not-instrumented"></div>

        <div id="d-instrumented" hidden>
          <!-- Plain text line, not a stat card - the signal bars below are
               the primary element on this page (spec). -->
          <p class="text-secondary" style="font-size:var(--text-sm);margin-bottom:var(--space-1)">
            <span id="d-share" class="mono" style="font-weight:var(--fw-semibold);color:var(--text)">&mdash;</span> of tracked features drifted &middot;
            last computed <span id="d-computed">&mdash;</span>
          </p>
          <div class="text-secondary" id="d-since" style="font-size:var(--text-sm);margin-bottom:var(--space-4)"></div>

          <div class="panel" style="margin-bottom:var(--space-4)">
            <div class="chart-panel-head">
              <div class="chart-panel-title">Drift share over time</div>
              <div class="chart-panel-meta">last 2 hours &middot; recomputed every 30 new predictions</div>
            </div>
            <canvas id="drift-chart" height="80"></canvas>
          </div>

          <div class="section-label" style="margin-top:0">Feature / distribution breakdown</div>
          <div id="breakdown-list" style="margin-bottom:var(--space-4)"></div>

          <div class="section-label">AI explanation</div>
          <div id="ai-analysis-surface" class="banner-strip" style="margin-bottom:var(--space-4)">
            <div id="ai-analysis-box" style="font-size:var(--text-sm);line-height:1.6">Loading&hellip;</div>
          </div>

          <div class="grid-2">
            <div>
              <div class="section-label" style="margin-top:0">What changed</div>
              <ul id="what-changed-list" style="font-size:var(--text-sm);line-height:1.8;padding-left:1.1rem;list-style:disc"></ul>
            </div>
            <div>
              <div class="section-label" style="margin-top:0">Recommended action</div>
              <ul id="recommended-list" style="font-size:var(--text-sm);line-height:1.8;padding-left:1.1rem;list-style:disc;margin-bottom:var(--space-3)"></ul>
              <a class="link-action link-primary" id="action-btn" href="#">Loading&hellip;</a>
            </div>
          </div>
        </div>
      </div>

      <div class="section-label">Summary</div>
      <div class="panel" id="mh-summary-card" style="margin-bottom:var(--space-4)">
        <div class="text-muted" style="font-size:var(--text-xs);margin-bottom:var(--space-2)">Auto-refreshes every 30s</div>
        <div id="summary-box" class="text-secondary" style="font-size:var(--text-sm);line-height:1.6">Loading summary&hellip;</div>
      </div>

      <div class="card-header">
        <div class="section-label" style="margin:0">Recent events</div>
        <span class="text-muted" id="timeline-status" style="font-size:var(--text-xs)"></span>
      </div>
      <div class="panel" id="timeline-list" style="max-height:280px;overflow-y:auto;margin-bottom:var(--space-4)"></div>
    </div>
  </div>
</div>
<div id="loading-root" style="min-height:100vh;display:flex;align-items:center;justify-content:center;color:var(--text-muted);font-size:var(--text-sm)">Loading&hellip;</div>
"""

MONITORING_SCRIPTS_EXTRA = MODEL_CATALOG_JS + f'\n<script src="/static/js/monitoring.js?v={_STATIC_V}"></script>'

# =========================================================================
# Documentation (spec §20) - same markup for admin and team-member; the
# model picker (which endpoint it lists models from) and whether an
# edit form appears below the card are the only things docs.js branches
# on role for. GET /model-cards/{id} itself still has no auth check -
# read access was never actually restricted, only whether you get an
# edit form is.
# =========================================================================

DOCS_BODY = """
<div id="page-content" hidden>
  <div class="page-max">
    <h1 style="font-size:var(--text-lg);margin-bottom:2px">Model Documentation</h1>
    <p class="text-secondary" style="font-size:var(--text-sm);margin-bottom:var(--space-5)" id="docs-subtitle">
      Select a model to view its documentation.
    </p>

    <div class="card" style="margin-bottom:var(--space-5)">
      <div class="field" style="margin-bottom:0">
        <label class="field-label" for="docs-model-select">Model</label>
        <select class="select" id="docs-model-select" style="min-width:280px"></select>
      </div>
    </div>

    <div id="card-result"></div>
  </div>
</div>
<div class="auth-loading" id="loading-root">Loading&hellip;</div>
"""

DOCS_SCRIPTS_EXTRA = f'<script src="/static/js/docs.js?v={_STATIC_V}"></script>'

# =========================================================================
# Settings (spec §18/§21) - identical for admin and team-member: account
# info + change password. See settings.js for the change-password
# endpoint's actual (no current-password check) behavior.
# =========================================================================

SETTINGS_BODY = """
<div id="page-content" hidden>
  <div class="page-max" style="max-width:560px">
    <h1 style="font-size:var(--text-lg);margin-bottom:var(--space-5)">Settings</h1>

    <div class="section-label" style="margin-top:0">Account</div>
    <div class="card" style="margin-bottom:var(--space-5)">
      <div style="display:flex;justify-content:space-between;padding:.45rem 0;border-bottom:1px solid var(--color-border-subtle)">
        <span class="text-secondary" style="font-size:var(--text-sm)">Username</span>
        <span id="acc-username" style="font-size:var(--text-sm)">&mdash;</span>
      </div>
      <div style="display:flex;justify-content:space-between;padding:.45rem 0;border-bottom:1px solid var(--color-border-subtle)">
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
      <form id="pw-form" novalidate>
        <div class="field"><label class="field-label" for="s-new-password">New password</label><input class="input" type="password" id="s-new-password" autocomplete="new-password" required minlength="8"></div>
        <div class="field"><label class="field-label" for="s-confirm-password">Confirm new password</label><input class="input" type="password" id="s-confirm-password" autocomplete="new-password" required minlength="8"></div>
        <div class="field-error" id="s-error" role="alert"></div>
        <button class="btn btn-primary" type="submit" id="s-submit">Update password</button>
      </form>
    </div>
  </div>
</div>
<div class="auth-loading" id="loading-root">Loading&hellip;</div>
"""

SETTINGS_SCRIPTS_EXTRA = '<script src="/static/js/settings.js"></script>'
