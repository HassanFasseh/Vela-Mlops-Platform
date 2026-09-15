/*
 * Vela application shell - persistent sidebar + top bar (spec §6).
 * Usage, from any authenticated page:
 *
 *   <div id="page-content" hidden> ...page markup... </div>
 *   <script src="/static/js/api.js"></script>
 *   <script src="/static/js/shell.js"></script>
 *   <script>
 *     Api.requireAuth().then(user => {
 *       if (!user) return;
 *       Shell.mount({ user, activePath: location.pathname,
 *                     breadcrumbs: [{label: 'Models'}] });
 *     });
 *   </script>
 *
 * The shell wraps whatever is inside #page-content - it never invents
 * page content itself. Only routes that already exist as backend pages
 * are linked from the nav; everything else here is a documented stub for
 * later implementation phases (spec §7/§9 information architecture).
 */

const Shell = (() => {
  // ---- Theme ---------------------------------------------------------
  // Dark is the default - no data-theme attribute matches :root in
  // tokens.css. "light" sets data-theme="light" to pick up the light
  // overrides there. Applied immediately below, as the first thing this
  // script does on load (before Shell.mount() or any async auth call
  // runs), so a stored "light" preference is already on <html> before
  // the "Loading…" spinner - the only thing visible pre-mount - ever
  // paints. Persists via localStorage and applies app-wide because every
  // page loads this same script.
  const THEME_KEY = "vela_theme";
  function currentTheme() {
    return document.documentElement.getAttribute("data-theme") === "light" ? "light" : "dark";
  }
  function applyTheme(theme) {
    if (theme === "light") document.documentElement.setAttribute("data-theme", "light");
    else document.documentElement.removeAttribute("data-theme");
  }
  (function initTheme() {
    let stored = null;
    try { stored = localStorage.getItem(THEME_KEY); } catch (e) {}
    applyTheme(stored === "light" ? "light" : "dark");
  })();

  const ICONS = {
    mark: '<svg viewBox="0 0 24 24" fill="currentColor"><path d="M4 20 L12 3 L12 20 Z"/></svg>',
    grid: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6"><rect x="3.5" y="3.5" width="7" height="7" rx="1"/><rect x="13.5" y="3.5" width="7" height="7" rx="1"/><rect x="3.5" y="13.5" width="7" height="7" rx="1"/><rect x="13.5" y="13.5" width="7" height="7" rx="1"/></svg>',
    box: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linejoin="round"><path d="M12 3 L20 7.5 V16.5 L12 21 L4 16.5 V7.5 Z"/><path d="M4 7.5 L12 12 L20 7.5"/><path d="M12 12 V21"/></svg>',
    layers: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linejoin="round"><path d="M12 3 L21 8 L12 13 L3 8 Z"/><path d="M3 13 L12 18 L21 13"/></svg>',
    activity: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><polyline points="3,13 8,13 10,7 14,19 16,13 21,13"/></svg>',
    trending: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><polyline points="3,17 10,10 14,14 21,6"/><polyline points="15,6 21,6 21,12"/></svg>',
    server: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6"><rect x="3.5" y="4" width="17" height="6" rx="1"/><rect x="3.5" y="14" width="17" height="6" rx="1"/><circle cx="7" cy="7" r=".8" fill="currentColor" stroke="none"/><circle cx="7" cy="17" r=".8" fill="currentColor" stroke="none"/></svg>',
    users: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6"><circle cx="9" cy="8" r="3"/><path d="M3 20c0-3.3 2.7-6 6-6s6 2.7 6 6"/><circle cx="17" cy="9" r="2.4"/><path d="M15.5 14c2.6.3 4.5 2.6 4.5 5.3"/></svg>',
    user: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6"><circle cx="12" cy="8" r="3.5"/><path d="M4.5 20c0-4.1 3.4-7.5 7.5-7.5s7.5 3.4 7.5 7.5"/></svg>',
    key: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"><circle cx="8" cy="15" r="4"/><path d="M11 12 L20 3"/><path d="M16 7 L19 10"/><path d="M13.5 9.5 L16 12"/></svg>',
    zap: '<svg viewBox="0 0 24 24" fill="currentColor" stroke="none"><path d="M13 2 L4 14 H11 L10 22 L20 9 H13 Z"/></svg>',
    link: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6"><rect x="3" y="9" width="9" height="6" rx="3"/><rect x="12" y="9" width="9" height="6" rx="3"/></svg>',
    refresh: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"><path d="M4 12a8 8 0 0 1 14-5.3L20 8"/><path d="M20 4v4h-4"/><path d="M20 12a8 8 0 0 1-14 5.3L4 16"/><path d="M4 20v-4h4"/></svg>',
    ticket: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linejoin="round"><path d="M3 8a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2v2a1.5 1.5 0 0 0 0 4v2a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-2a1.5 1.5 0 0 0 0-4Z"/></svg>',
    book: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linejoin="round"><path d="M4 5.5A2.5 2.5 0 0 1 6.5 3H12v18H6.5A2.5 2.5 0 0 0 4 23.5Z"/><path d="M20 5.5A2.5 2.5 0 0 0 17.5 3H12v18h5.5a2.5 2.5 0 0 1 2.5 2.5Z"/></svg>',
    settings: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6"><circle cx="12" cy="12" r="3"/><path d="M12 3v2.4M12 18.6V21M21 12h-2.4M5.4 12H3M18.4 5.6l-1.7 1.7M7.3 16.7l-1.7 1.7M18.4 18.4l-1.7-1.7M7.3 7.3 5.6 5.6"/></svg>',
    bell: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linejoin="round"><path d="M6 10a6 6 0 0 1 12 0c0 4.5 1.5 6 1.5 6h-15S6 14.5 6 10Z"/><path d="M9.5 19a2.5 2.5 0 0 0 5 0"/></svg>',
    sun: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"><circle cx="12" cy="12" r="4.5"/><path d="M12 2.5v3M12 18.5v3M4.2 4.2l2.1 2.1M17.7 17.7l2.1 2.1M2.5 12h3M18.5 12h3M4.2 19.8l2.1-2.1M17.7 6.3l2.1-2.1"/></svg>',
    moon: '<svg viewBox="0 0 24 24" fill="currentColor" stroke="none"><path d="M20.5 14.5A8.5 8.5 0 0 1 9.5 3.5a8.5 8.5 0 1 0 11 11Z"/></svg>',
    check: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><polyline points="5,13 10,18 19,7"/></svg>',
    clock: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="8.5"/><path d="M12 7.5V12l3 2"/></svg>',
    chevronDown: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><polyline points="6,9 12,15 18,9"/></svg>',
    menu: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"><line x1="4" y1="7" x2="20" y2="7"/><line x1="4" y1="12" x2="20" y2="12"/><line x1="4" y1="17" x2="20" y2="17"/></svg>',
  };

  function icon(name) {
    return `<span class="shell-nav-item-icon" aria-hidden="true">${ICONS[name] || ""}</span>`;
  }

  // Sun/moon + a plain-language label, e.g. "Dark theme" - both the icon
  // and the answer are always the state you're CURRENTLY in, matching
  // the labeled dot+text convention used everywhere else (statusBadge).
  // Lives in the user dropdown (not the sidebar), so its text is a plain
  // span - not .shell-nav-label, which .shell.is-collapsed hides and
  // would otherwise wrongly reach into this unrelated topbar dropdown.
  function themeToggleInner() {
    const light = currentTheme() === "light";
    return `${icon(light ? "sun" : "moon")}<span>${light ? "Light theme" : "Dark theme"}</span>`;
  }

  const NAV = {
    admin: [
      { items: [{ label: "Overview", href: "/admin", icon: "grid" }] },
      {
        label: "Models",
        items: [
          { label: "Registry", href: "/admin/models", icon: "box" },
          { label: "Deployments", href: "/admin/deployments", icon: "layers" },
        ],
      },
      {
        label: "Monitoring",
        items: [
          { label: "Model Health", href: "/admin/monitoring", icon: "activity" },
          { label: "Infrastructure", href: "/admin/infrastructure", icon: "server" },
        ],
      },
      {
        label: "Teams & Access",
        items: [
          { label: "Teams", href: "/admin/teams-page", icon: "users" },
          { label: "Users", href: "/admin/users-page", icon: "user" },
          { label: "API Keys", href: "/admin/api-keys", icon: "key" },
        ],
      },
      {
        label: "Automation",
        items: [
          { label: "Remediation", href: "/admin/remediation", icon: "zap" },
        ],
      },
      {
        items: [
          { label: "History", href: "/admin/history", icon: "clock" },
          { label: "Tickets", href: "/admin/tickets-page", icon: "ticket" },
          { label: "Documentation", href: "/admin/docs", icon: "book" },
          { label: "Settings", href: "/admin/settings", icon: "settings" },
        ],
      },
    ],
    member: [
      { items: [{ label: "Overview", href: "/app", icon: "grid" }] },
      {
        items: [
          { label: "My Models", href: "/app/models", icon: "box", expandable: true, key: "models" },
        ],
      },
      {
        items: [
          { label: "History", href: "/app/history", icon: "clock" },
          { label: "Tickets", href: "/app/tickets", icon: "ticket" },
          { label: "API Keys", href: "/app/api-keys", icon: "key" },
          { label: "Documentation", href: "/app/docs", icon: "book" },
          { label: "Settings", href: "/app/settings", icon: "settings" },
        ],
      },
    ],
  };

  function escapeHtml(str) {
    return String(str == null ? "" : str).replace(/[&<>"']/g, (c) => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
    }[c]));
  }

  function initials(name) {
    const parts = String(name || "?").trim().split(/\s+/).filter(Boolean);
    if (!parts.length) return "?";
    return (parts[0][0] + (parts[1] ? parts[1][0] : "")).toUpperCase();
  }

  function isActive(href, activePath) {
    if (href === activePath) return true;
    // treat a nested path as "active" for its nearest parent nav item,
    // but never let the bare overview item ("/admin", "/app") light up
    // for every sub-route.
    if (href === "/admin" || href === "/app") return false;
    return activePath.indexOf(href + "/") === 0;
  }

  // Member's accessible-model rows, deduped by deployment_id - the exact
  // logic /app/models used to run itself before model selection moved into
  // this sidebar dropdown. Shared here (instead of duplicated per page) so
  // both the sidebar list and the /app/models/{id} detail page see the same
  // data. Fetched lazily (only once "My Models" is actually expanded, see
  // wireEvents) and cached for the life of this page load - a fresh
  // navigation re-fetches, which is fine, this is cheap.
  let _memberModelRowsPromise = null;
  function fetchMemberModelRows() {
    if (!_memberModelRowsPromise) {
      _memberModelRowsPromise = (async () => {
        const teams = await Api.get("/users/me/teams");
        if (!teams.length) return [];
        const perTeam = await Promise.allSettled(
          teams.map((t) => Api.get("/teams/" + t.id + "/permissions").then((perms) =>
            perms.map((p) => Object.assign({}, p, { team_id: t.id, team_name: t.name }))
          ))
        );
        const byDeployment = new Map();
        perTeam.forEach((result) => {
          if (result.status !== "fulfilled") return;
          result.value.forEach((p) => {
            // Admin "Disable" (/admin/models) hides a model from members
            // entirely - see the matching filter on /app/teams/{id}.
            if (p.is_active === false) return;
            if (!byDeployment.has(p.deployment_id)) byDeployment.set(p.deployment_id, p);
          });
        });
        return Array.from(byDeployment.values());
      })().catch((e) => {
        // Don't leave a rejected promise cached - the next expand attempt
        // (or the detail page's own call) should get to retry the fetch.
        _memberModelRowsPromise = null;
        throw e;
      });
    }
    return _memberModelRowsPromise;
  }

  function renderNavItem(item, activePath) {
    const active = isActive(item.href, activePath) ? " is-active" : "";
    if (item.expandable) {
      return (
        `<div class="shell-nav-item shell-nav-toggle${active}" data-nav-toggle="${item.key}" role="button" tabindex="0" aria-expanded="false" aria-controls="shell-nav-sub-${item.key}">` +
        `${icon(item.icon)}<span class="shell-nav-label">${escapeHtml(item.label)}</span>` +
        `<span class="shell-nav-chevron" aria-hidden="true">${ICONS.chevronDown}</span></div>` +
        `<div class="shell-nav-subtree" id="shell-nav-sub-${item.key}" data-nav-subtree="${item.key}" hidden></div>`
      );
    }
    return `<a class="shell-nav-item${active}" href="${item.href}">${icon(item.icon)}<span class="shell-nav-label">${escapeHtml(item.label)}</span></a>`;
  }

  function renderNav(role, activePath) {
    const sections = NAV[role] || NAV.member;
    return sections
      .map((section) => {
        const label = section.label
          ? `<div class="shell-nav-section-label">${escapeHtml(section.label)}</div>`
          : "";
        const items = section.items.map((item) => renderNavItem(item, activePath)).join("");
        return label + items;
      })
      .join("");
  }

  function renderBreadcrumbs(crumbs) {
    if (!crumbs || !crumbs.length) return "";
    return crumbs
      .map((c, i) => {
        const isLast = i === crumbs.length - 1;
        if (isLast || !c.href) {
          return `<span class="shell-breadcrumb-current">${escapeHtml(c.label)}</span>`;
        }
        return `<a href="${c.href}">${escapeHtml(c.label)}</a><span aria-hidden="true">/</span>`;
      })
      .join(" ");
  }

  function mount({ user, activePath, breadcrumbs = [], notificationCount = 0 }) {
    const role = user && user.is_admin ? "admin" : "member";
    const pageContent = document.getElementById("page-content");
    if (!pageContent) {
      console.error("Shell.mount: no #page-content element found");
      return;
    }
    pageContent.remove();

    let collapsed = false;
    try {
      collapsed = localStorage.getItem("vela_sidebar_collapsed") === "1";
    } catch (e) {}

    document.body.innerHTML = "";

    const skipLink = document.createElement("a");
    skipLink.className = "shell-skip-link";
    skipLink.href = "#shell-main";
    skipLink.textContent = "Skip to main content";
    document.body.appendChild(skipLink);

    const shell = document.createElement("div");
    shell.className = "shell" + (collapsed ? " is-collapsed" : "");
    shell.innerHTML = `
      <aside class="shell-sidebar">
        <div class="shell-brand">
          <span class="shell-brand-mark">${ICONS.mark}</span>
          <span class="shell-brand-name">VELA</span>
        </div>
        <nav class="shell-nav" aria-label="Primary">${renderNav(role, activePath)}</nav>
        <button class="shell-collapse-btn" id="shell-collapse-btn" type="button" aria-label="Toggle sidebar width">
          ${icon("menu")}<span class="shell-nav-label">Collapse</span>
        </button>
        <a class="shell-sidebar-footer" href="${role === "admin" ? "/admin/settings" : "/app/settings"}">
          <span class="shell-sidebar-footer-text">
            <div class="shell-sidebar-footer-name">${escapeHtml(user.name || user.username)}</div>
            <div class="shell-sidebar-footer-role">${role === "admin" ? "Administrator" : "Member"}</div>
          </span>
          <span class="shell-sidebar-footer-icon" aria-hidden="true">${ICONS.settings}</span>
        </a>
      </aside>
      <div class="shell-body">
        <header class="shell-topbar">
          <button class="shell-mobile-toggle" id="shell-mobile-toggle" type="button" aria-label="Open navigation menu" aria-expanded="false">
            ${icon("menu")}
          </button>
          <nav class="shell-breadcrumbs" aria-label="Breadcrumb">${renderBreadcrumbs(breadcrumbs)}</nav>
          <div class="shell-topbar-spacer"></div>
          <div class="shell-topbar-actions">
            <div class="shell-notif-menu" id="shell-notif-menu"${role === "admin" ? "" : " hidden"}>
              <button class="shell-icon-btn" id="shell-notif-btn" type="button" aria-label="Notifications" aria-haspopup="true" aria-expanded="false">
                ${ICONS.bell}<span class="shell-notif-dot" id="shell-notif-dot" hidden></span>
              </button>
              <div class="dropdown-menu shell-notif-panel" id="shell-notif-panel" hidden>
                <div class="shell-notif-panel-header">
                  <span>Notifications</span>
                  <button class="link-action" id="shell-notif-mark-all" type="button">Mark all read</button>
                </div>
                <div class="shell-notif-panel-body" id="shell-notif-body"></div>
              </div>
            </div>
            <div class="shell-user-menu">
              <button class="shell-user-btn" id="shell-user-btn" type="button" aria-haspopup="true" aria-expanded="false">
                <span class="shell-avatar">${escapeHtml(initials(user.name))}</span>
                ${icon("chevronDown")}
              </button>
              <div class="dropdown-menu shell-user-dropdown" id="shell-user-dropdown" hidden>
                <div class="shell-user-dropdown-header">
                  <div class="shell-user-dropdown-name">${escapeHtml(user.name)}</div>
                  <div class="shell-user-dropdown-role">${user.is_admin ? "Administrator" : "Team member"}</div>
                </div>
                <button class="dropdown-item" id="shell-theme-toggle" type="button"
                  role="menuitemcheckbox" aria-checked="${currentTheme() === "light"}">
                  ${themeToggleInner()}
                </button>
                <div class="dropdown-divider"></div>
                <a class="dropdown-item" href="/change-password">Change password</a>
                <button class="dropdown-item" id="shell-logout-btn" type="button">Log out</button>
              </div>
            </div>
          </div>
        </header>
        <main class="shell-main" id="shell-main" tabindex="-1"></main>
      </div>
    `;

    document.body.appendChild(shell);
    const main = shell.querySelector("#shell-main");
    pageContent.hidden = false;
    main.appendChild(pageContent);

    wireEvents(shell, role);

    // Admin-only, cheap sources only (tickets + remediation logs) - just
    // enough to light the unread dot on every page load without adding
    // the expensive per-model health probe to every navigation. See
    // notifications.js for the full aggregation + the health probe,
    // which only runs once the panel is actually opened.
    if (role === "admin" && typeof Notifications !== "undefined") {
      Notifications.init({
        dotEl: shell.querySelector("#shell-notif-dot"),
        bodyEl: shell.querySelector("#shell-notif-body"),
      });
    }

    // Added last, after the whole shell subtree is in place - both the
    // light dashboard theme (tokens.css: body.has-shell token overrides)
    // and the shell layout lock (shell.css: body.has-shell { overflow:
    // hidden; height:100vh }) key off this class, so it must land after
    // the document.body.innerHTML reset above and after every element
    // that needs to inherit those tokens has already been appended.
    document.body.classList.add("has-shell");
  }

  function wireEvents(shell, role) {
    // Sidebar collapse (desktop)
    const collapseBtn = shell.querySelector("#shell-collapse-btn");
    collapseBtn.addEventListener("click", () => {
      const collapsed = shell.classList.toggle("is-collapsed");
      try {
        localStorage.setItem("vela_sidebar_collapsed", collapsed ? "1" : "0");
      } catch (e) {}
    });

    // Sidebar off-canvas (mobile)
    const mobileToggle = shell.querySelector("#shell-mobile-toggle");
    mobileToggle.addEventListener("click", () => {
      const open = shell.classList.toggle("is-mobile-open");
      mobileToggle.setAttribute("aria-expanded", String(open));
    });
    // Expandable "My Models" excluded here - clicking it opens the dropdown
    // in place, it shouldn't also close the drawer out from under that.
    // Model links inside the dropdown (added later, once expanded - see
    // below) get their own identical close-on-click wiring.
    shell.querySelectorAll(".shell-nav-item:not(.shell-nav-toggle)").forEach((el) => {
      el.addEventListener("click", () => {
        shell.classList.remove("is-mobile-open");
        mobileToggle.setAttribute("aria-expanded", "false");
      });
    });
    document.addEventListener("keydown", (e) => {
      if (e.key === "Escape" && shell.classList.contains("is-mobile-open")) {
        shell.classList.remove("is-mobile-open");
        mobileToggle.setAttribute("aria-expanded", "false");
      }
    });

    // Expandable nav sections - currently just "My Models". Collapsed into
    // its own block since (unlike every other nav item) it doesn't navigate
    // on click, it toggles a subtree of model links fetched lazily the
    // first time it's opened.
    shell.querySelectorAll("[data-nav-toggle]").forEach((toggle) => {
      const key = toggle.dataset.navToggle;
      const subtree = shell.querySelector('[data-nav-subtree="' + key + '"]');
      if (!subtree) return;
      let loaded = false;

      function setExpanded(expanded) {
        toggle.setAttribute("aria-expanded", String(expanded));
        toggle.classList.toggle("is-expanded", expanded);
        subtree.hidden = !expanded;
      }

      async function ensureLoaded() {
        if (loaded) return;
        loaded = true;
        subtree.innerHTML = '<div class="shell-nav-subtree-status">Loading&hellip;</div>';
        try {
          const rows = key === "models" ? await fetchMemberModelRows() : [];
          if (!rows.length) {
            subtree.innerHTML = '<div class="shell-nav-subtree-status">No models yet</div>';
            return;
          }
          subtree.innerHTML = rows
            .map((r) => {
              const href = "/app/models/" + r.deployment_id;
              const active = isActive(href, location.pathname) ? " is-active" : "";
              return `<a class="shell-nav-item shell-nav-subitem${active}" href="${href}" title="${escapeHtml(r.model_name)}">${escapeHtml(r.model_name)}</a>`;
            })
            .join("");
          subtree.querySelectorAll(".shell-nav-item").forEach((el) => {
            el.addEventListener("click", () => {
              shell.classList.remove("is-mobile-open");
              mobileToggle.setAttribute("aria-expanded", "false");
            });
          });
        } catch (e) {
          loaded = false; // let the next expand retry instead of getting stuck
          subtree.innerHTML = '<div class="shell-nav-subtree-status shell-nav-subtree-error">Couldn&rsquo;t load models</div>';
        }
      }

      function toggleExpanded() {
        // A 56px collapsed rail has nowhere to show a model list - widen
        // the sidebar first (same mechanism as the manual collapse button)
        // rather than build a separate flyout for this one case.
        if (shell.classList.contains("is-collapsed")) {
          shell.classList.remove("is-collapsed");
          try { localStorage.setItem("vela_sidebar_collapsed", "0"); } catch (e) {}
        }
        const expanded = toggle.getAttribute("aria-expanded") === "true";
        setExpanded(!expanded);
        if (!expanded) ensureLoaded();
      }

      toggle.addEventListener("click", toggleExpanded);
      toggle.addEventListener("keydown", (e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          toggleExpanded();
        }
      });

      // Already viewing a page under this section (e.g. a model's detail
      // page) - start expanded and loaded so the active one is visible
      // without an extra click.
      if (toggle.classList.contains("is-active")) {
        setExpanded(true);
        ensureLoaded();
      }
    });

    // Theme toggle - lives in the user dropdown now; clicking it flips
    // the theme in place without closing the menu (it's not in
    // userDropdown's outside-click path since it's inside userDropdown).
    const themeToggleBtn = shell.querySelector("#shell-theme-toggle");
    themeToggleBtn.addEventListener("click", () => {
      const next = currentTheme() === "light" ? "dark" : "light";
      applyTheme(next);
      try { localStorage.setItem(THEME_KEY, next); } catch (e) {}
      themeToggleBtn.innerHTML = themeToggleInner();
      themeToggleBtn.setAttribute("aria-checked", String(next === "light"));
    });

    // User menu
    const userBtn = shell.querySelector("#shell-user-btn");
    const userDropdown = shell.querySelector("#shell-user-dropdown");
    userBtn.addEventListener("click", (e) => {
      e.stopPropagation();
      const open = !userDropdown.hidden;
      userDropdown.hidden = open;
      userBtn.setAttribute("aria-expanded", String(!open));
    });
    document.addEventListener("click", (e) => {
      if (!userDropdown.hidden && !userDropdown.contains(e.target) && e.target !== userBtn) {
        userDropdown.hidden = true;
        userBtn.setAttribute("aria-expanded", "false");
      }
    });
    shell.querySelector("#shell-logout-btn").addEventListener("click", () => Api.logout());

    // Notifications - admin-only (the menu is hidden in the template
    // above for members, and notifications.js isn't even loaded on
    // member pages - see _SCRIPTS in member_pages.py).
    if (role === "admin" && typeof Notifications !== "undefined") {
      const notifBtn = shell.querySelector("#shell-notif-btn");
      const notifPanel = shell.querySelector("#shell-notif-panel");
      notifBtn.addEventListener("click", (e) => {
        e.stopPropagation();
        const open = !notifPanel.hidden;
        notifPanel.hidden = open;
        notifBtn.setAttribute("aria-expanded", String(!open));
        if (!open) Notifications.onPanelOpen();
      });
      document.addEventListener("click", (e) => {
        if (!notifPanel.hidden && !notifPanel.contains(e.target) && e.target !== notifBtn) {
          notifPanel.hidden = true;
          notifBtn.setAttribute("aria-expanded", "false");
        }
      });
      shell.querySelector("#shell-notif-mark-all").addEventListener("click", () => Notifications.markAllRead());
    }
  }

  return { mount, ICONS, icon, escapeHtml, initials, fetchMemberModelRows };
})();
