"""
Shared HTML fragments used by more than one page router (admin_pages.py,
member_pages.py).

Model Health and Drift are model-centric (spec redesign): both pages open
on a model picker (models.js' ModelCatalog — composed client-side from
existing endpoints, scoped per role) and render one model's evidence at a
time, never a platform-wide rollup. Node CPU/memory and the services list
are deliberately NOT here any more — that's system/infrastructure
monitoring, and it already has a real home at /admin/infrastructure
(admin-only). See monitoring.js/drift.js for what's real vs. honestly
marked "not instrumented" — only one Prometheus job exists in this
backend today (services/timeline.py's DEFAULT_JOB).
"""

CHART_JS_CDN = '<script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.min.js"></script>'

# Cache-busting query param on our own monitoring/drift static assets only
# (third-party CDN URLs above are already version-pinned in their path).
# These files are served from a fixed URL with no content hash, so a
# browser or intermediate proxy that cached the pre-redesign monitoring.js
# against that same URL would keep serving it after a redeploy — same
# HTML (fresh, since FastAPI never caches it), stale JS silently doing
# nothing with the new page's element ids. Bump this string on every
# change to these files.
_STATIC_V = "7"
MONITORING_CSS = f'<link rel="stylesheet" href="/static/css/monitoring.css?v={_STATIC_V}">'
MODEL_CATALOG_JS = f'<script src="/static/js/models.js?v={_STATIC_V}"></script>'

MONITORING_BODY = """
<div id="page-content" hidden>
  <div class="page-max">
    <h1 style="font-size:var(--text-lg);margin-bottom:2px">Model Health</h1>
    <p class="text-secondary" style="font-size:var(--text-sm);margin-bottom:var(--space-4)">
      Pick a model to see whether it's healthy, what changed recently, and whether it needs attention.
    </p>

    <div class="evidence-panel" style="margin-bottom:var(--space-4)">
      <div id="model-picker"></div>
    </div>

    <div id="model-empty"></div>

    <div id="model-content" hidden>
      <div class="evidence-panel" style="margin-bottom:var(--space-4)">
        <div class="model-header">
          <span class="model-header-name" id="mh-name">&mdash;</span>
          <span id="mh-status-badge"></span>
        </div>
        <div class="model-header-task" id="mh-task"></div>
        <div class="stat-line-row" id="mh-status-stats" style="margin-top:var(--space-3)"></div>
      </div>

      <div id="mh-performance"></div>

      <div class="card-header" style="margin-top:var(--space-5)">
        <div class="section-label" style="margin:0">Drift</div>
        <a class="link-secondary" style="font-size:var(--text-sm)" id="mh-drift-link" href="/app/drift">Full drift analysis &rarr;</a>
      </div>
      <div class="evidence-panel" id="mh-drift-teaser" style="margin-bottom:var(--space-5)"></div>

      <div class="section-label">Summary</div>
      <div class="evidence-panel" style="border-left:3px solid var(--color-accent);margin-bottom:var(--space-5)" id="mh-summary-card">
        <div class="text-muted" style="font-size:var(--text-xs);margin-bottom:.4rem">Auto-refreshes every 30s</div>
        <div id="summary-box" class="text-secondary" style="font-size:var(--text-sm);line-height:1.6">Loading summary&hellip;</div>
      </div>

      <div class="card-header">
        <div class="section-label" style="margin:0">Recent events</div>
        <span class="text-muted" id="timeline-status" style="font-size:var(--text-xs)"></span>
      </div>
      <div class="evidence-panel" id="timeline-list" style="max-height:280px;overflow-y:auto;margin-bottom:var(--space-5)"></div>
    </div>
  </div>
</div>
<div class="auth-loading" id="loading-root">Loading&hellip;</div>
"""

MONITORING_SCRIPTS_EXTRA = MODEL_CATALOG_JS + f'\n<script src="/static/js/monitoring.js?v={_STATIC_V}"></script>'

# =========================================================================
# Drift — the standout page (spec goal #5): what changed, which features,
# how much, since when, an AI explanation, and what to do about it — for
# whichever one model is selected. Shares its model picker/state with
# Model Health via ModelCatalog (models.js), not a separate selection.
# =========================================================================

DRIFT_BODY = """
<div id="page-content" hidden>
  <div class="page-max">
    <h1 style="font-size:var(--text-lg);margin-bottom:2px">Drift</h1>
    <p class="text-secondary" style="font-size:var(--text-sm);margin-bottom:var(--space-4)">
      What changed in this model's inputs and outputs since its reference window, and why.
    </p>

    <div class="evidence-panel" style="margin-bottom:var(--space-4)">
      <div id="model-picker"></div>
    </div>

    <div id="model-empty"></div>

    <div id="drift-content" hidden>
      <div class="evidence-panel" style="margin-bottom:var(--space-4)">
        <div class="model-header">
          <span class="model-header-name" id="d-name">&mdash;</span>
          <span id="d-status-badge"></span>
        </div>
        <div class="model-header-task" id="d-task"></div>
      </div>

      <div id="d-not-instrumented"></div>

      <div id="d-instrumented" hidden>
        <div class="evidence-panel" style="margin-bottom:var(--space-4)">
          <div class="stat-line-row">
            <div class="stat-line"><div class="stat-line-value" id="d-share">&mdash;</div><div class="stat-line-label">Share of tracked features drifted</div></div>
            <div class="stat-line"><div class="stat-line-value" id="d-computed" style="font-size:var(--text-sm)">&mdash;</div><div class="stat-line-label">Last computed</div></div>
          </div>
          <div class="since-strip" id="d-since"></div>
        </div>

        <div class="evidence-panel" style="margin-bottom:var(--space-4)">
          <div class="chart-panel-head">
            <div class="chart-panel-title">Drift share over time</div>
            <div class="chart-panel-meta">last 2 hours &middot; recomputed every 30 new predictions</div>
          </div>
          <canvas id="drift-chart" height="80"></canvas>
        </div>

        <div class="section-label">Feature / distribution breakdown</div>
        <div class="evidence-panel" style="margin-bottom:var(--space-5)" id="breakdown-list"></div>

        <div class="section-label">AI explanation</div>
        <div class="evidence-panel" style="border-left:3px solid var(--color-accent);margin-bottom:var(--space-5)">
          <div id="ai-analysis-box" class="text-secondary" style="font-size:var(--text-sm);line-height:1.6">Loading&hellip;</div>
        </div>

        <div class="grid-2">
          <div class="evidence-panel">
            <div class="section-label" style="margin-top:0">What changed</div>
            <ul id="what-changed-list" style="font-size:var(--text-sm);line-height:1.8;padding-left:1.1rem;list-style:disc"></ul>
          </div>
          <div class="evidence-panel">
            <div class="section-label" style="margin-top:0">Recommended action</div>
            <ul id="recommended-list" style="font-size:var(--text-sm);line-height:1.8;padding-left:1.1rem;list-style:disc;margin-bottom:.75rem"></ul>
            <a class="btn btn-primary btn-sm" id="action-btn" href="#">Loading&hellip;</a>
          </div>
        </div>
      </div>
    </div>
  </div>
</div>
<div class="auth-loading" id="loading-root">Loading&hellip;</div>
"""

DRIFT_SCRIPTS_EXTRA = MODEL_CATALOG_JS + f'\n<script src="/static/js/drift.js?v={_STATIC_V}"></script>'

# =========================================================================
# Documentation (spec §20) — identical for admin and team-member: model
# cards aren't role-scoped in the backend (GET /model-cards/{id} has no
# auth check at all), so there's nothing to differentiate.
# =========================================================================

DOCS_BODY = """
<div id="page-content" hidden>
  <div class="page-max">
    <h1 style="font-size:var(--text-lg);margin-bottom:2px">Model Documentation</h1>
    <p class="text-secondary" style="font-size:var(--text-sm);margin-bottom:var(--space-5)">
      Look up a model card by deployment ID.
    </p>

    <div class="card" style="margin-bottom:var(--space-5)">
      <form id="lookup-form" style="display:flex;gap:var(--space-3);align-items:end;flex-wrap:wrap">
        <div class="field" style="margin-bottom:0;flex:1;min-width:160px">
          <label class="field-label" for="dep-id">Deployment ID</label>
          <input class="input" type="number" id="dep-id" required>
        </div>
        <button class="btn btn-primary" type="submit">Look up</button>
      </form>
    </div>

    <div id="card-result"></div>
  </div>
</div>
<div class="auth-loading" id="loading-root">Loading&hellip;</div>
"""

DOCS_SCRIPTS_EXTRA = f'<script src="/static/js/docs.js?v={_STATIC_V}"></script>'

# =========================================================================
# Settings (spec §18/§21) — identical for admin and team-member: account
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
