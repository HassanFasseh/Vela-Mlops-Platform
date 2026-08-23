"""
Shared HTML fragments used by more than one page router (admin_pages.py,
member_pages.py). Kept out of both since the Monitoring page is identical
content for admin and team-member — same platform-wide infrastructure
metrics, no team scoping exists for these (unlike the Models list, CPU/
drift/latency aren't a per-user resource to begin with).
"""

CHART_JS_CDN = '<script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.min.js"></script>'

MONITORING_BODY = """
<div id="page-content" hidden>
  <div class="page-max">
    <h1 style="font-size:var(--text-lg);margin-bottom:2px">Model Health</h1>
    <p class="text-secondary" style="font-size:var(--text-sm);margin-bottom:var(--space-5)">Live platform metrics, refreshed every 30 seconds.</p>

    <div class="metric-row" style="margin-bottom:var(--space-4)">
      <div class="metric-tile"><div class="metric-tile-value" id="m-rate">&mdash;</div><div class="metric-tile-label">Predictions / min</div></div>
      <div class="metric-tile"><div class="metric-tile-value" id="m-latency">&mdash;</div><div class="metric-tile-label">p95 latency (ms)</div></div>
      <div class="metric-tile"><div class="metric-tile-value" id="m-drift">&mdash;</div><div class="metric-tile-label">Drift score</div></div>
      <div class="metric-tile"><div class="metric-tile-value" id="m-total">&mdash;</div><div class="metric-tile-label">Total predictions</div></div>
    </div>

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

    <div class="grid-2" style="margin-bottom:var(--space-4)">
      <div class="card chart-card">
        <div class="card-title" style="margin-bottom:.6rem">Drift score &mdash; last 2 hours</div>
        <canvas id="drift-chart" height="90"></canvas>
      </div>
      <div class="card chart-card">
        <div class="card-title" style="margin-bottom:.6rem">p95 latency &mdash; last 6 hours</div>
        <canvas id="latency-chart" height="90"></canvas>
      </div>
    </div>

    <div class="card" id="drift-details-wrap" hidden style="margin-bottom:var(--space-4)">
      <div class="card-title" style="margin-bottom:.5rem">Population-level drift breakdown</div>
      <div id="drift-details-content"></div>
    </div>

    <div class="section-label">Infrastructure</div>
    <div class="card-grid" id="model-status-grid" style="margin-bottom:var(--space-5)"></div>

    <div class="section-label">LLM summary</div>
    <div class="card" style="border-left:3px solid var(--color-accent);margin-bottom:var(--space-5)">
      <div class="text-muted" style="font-size:var(--text-xs);margin-bottom:.4rem">Auto-refreshes every 30s</div>
      <div id="summary-box" class="text-secondary" style="font-size:var(--text-sm);line-height:1.6">Loading summary&hellip;</div>
    </div>

    <div class="card-header">
      <div class="section-label" style="margin:0">Operations timeline</div>
      <span class="text-muted" id="timeline-status" style="font-size:var(--text-xs)"></span>
    </div>
    <ul id="timeline-list" style="max-height:320px;overflow-y:auto"></ul>
  </div>
</div>
<div class="auth-loading" id="loading-root">Loading&hellip;</div>
"""

MONITORING_SCRIPTS_EXTRA = '<script src="/static/js/monitoring.js"></script>'

# =========================================================================
# Drift analysis (spec §13/§14) — identical for admin and team-member for
# the same reason as Monitoring: there is exactly one drift signal in this
# backend (get_drift_details() always queries MODEL_SERVICE_URL, the core
# sentiment service — there's no per-deployment or per-model drift
# endpoint), so there's nothing to scope per role or per team.
# =========================================================================

DRIFT_BODY = """
<div id="page-content" hidden>
  <div class="page-max">
    <h1 style="font-size:var(--text-lg);margin-bottom:2px">Drift Analysis</h1>
    <p class="text-secondary" style="font-size:var(--text-sm);margin-bottom:var(--space-5)">
      Computed against the platform's primary sentiment model. This is currently the only model instrumented for drift detection.
    </p>

    <div class="metric-row" style="margin-bottom:var(--space-4)">
      <div class="metric-tile"><div class="metric-tile-value" id="drift-score-value">&mdash;</div><div class="metric-tile-label">Overall drift score</div></div>
      <div class="metric-tile"><div class="metric-tile-value" id="detection-status" style="font-size:var(--text-md)">&mdash;</div><div class="metric-tile-label">Detection status</div></div>
    </div>

    <div class="card" style="margin-bottom:var(--space-4)">
      <div class="section-label" style="margin-top:0">Drift overview</div>
      <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:var(--space-4)">
        <div><div class="field-label">Threshold</div><div id="detection-threshold" style="font-size:var(--text-sm);margin-top:2px">&mdash;</div></div>
        <div><div class="field-label">Statistical test</div><div id="statistical-test" style="font-size:var(--text-sm);margin-top:2px">&mdash;</div></div>
        <div><div class="field-label">Time detected</div><div id="time-detected" style="font-size:var(--text-sm);margin-top:2px">&mdash;</div></div>
        <div><div class="field-label">Raw score</div><div id="drift-score-raw" style="font-size:var(--text-sm);margin-top:2px">&mdash;</div></div>
      </div>
    </div>

    <div class="section-label">Population / feature breakdown</div>
    <div class="table-wrap" style="margin-bottom:var(--space-5)">
      <table class="table">
        <thead><tr><th>Signal</th><th>Method</th><th>p-value</th><th>Status</th></tr></thead>
        <tbody id="breakdown-body"></tbody>
      </table>
    </div>

    <div class="card" style="border-left:3px solid var(--color-accent);margin-bottom:var(--space-5)">
      <div class="card-title" style="margin-bottom:.5rem">AI Analysis</div>
      <div id="ai-analysis-box" class="text-secondary" style="font-size:var(--text-sm);line-height:1.6">Loading&hellip;</div>
    </div>

    <div class="grid-2">
      <div class="card">
        <div class="section-label" style="margin-top:0">What changed</div>
        <ul id="what-changed-list" style="font-size:var(--text-sm);line-height:1.8;padding-left:1.1rem;list-style:disc"></ul>
      </div>
      <div class="card">
        <div class="section-label" style="margin-top:0">Recommended action</div>
        <ul id="recommended-list" style="font-size:var(--text-sm);line-height:1.8;padding-left:1.1rem;list-style:disc;margin-bottom:.75rem"></ul>
        <a class="btn btn-primary btn-sm" id="action-btn" href="#">Loading&hellip;</a>
      </div>
    </div>
  </div>
</div>
<div class="auth-loading" id="loading-root">Loading&hellip;</div>
"""

DRIFT_SCRIPTS_EXTRA = '<script src="/static/js/drift.js"></script>'

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

DOCS_SCRIPTS_EXTRA = '<script src="/static/js/docs.js"></script>'

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
