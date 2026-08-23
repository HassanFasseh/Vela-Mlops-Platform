/*
 * Vela application shell — persistent sidebar + top bar (spec §6).
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
 * The shell wraps whatever is inside #page-content — it never invents
 * page content itself. Only routes that already exist as backend pages
 * are linked from the nav; everything else here is a documented stub for
 * later implementation phases (spec §7/§9 information architecture).
 */

const Shell = (() => {
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
    search: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6"><circle cx="10.5" cy="10.5" r="6.5"/><path d="M20 20 L15.5 15.5"/></svg>',
    bell: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linejoin="round"><path d="M6 10a6 6 0 0 1 12 0c0 4.5 1.5 6 1.5 6h-15S6 14.5 6 10Z"/><path d="M9.5 19a2.5 2.5 0 0 0 5 0"/></svg>',
    chevronDown: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><polyline points="6,9 12,15 18,9"/></svg>',
    menu: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"><line x1="4" y1="7" x2="20" y2="7"/><line x1="4" y1="12" x2="20" y2="12"/><line x1="4" y1="17" x2="20" y2="17"/></svg>',
  };

  function icon(name) {
    return `<span class="shell-nav-item-icon" aria-hidden="true">${ICONS[name] || ""}</span>`;
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
          { label: "Drift", href: "/admin/drift", icon: "trending" },
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
          { label: "My Models", href: "/app/models", icon: "box" },
          { label: "Monitoring", href: "/app/monitoring", icon: "activity" },
          { label: "Drift", href: "/app/drift", icon: "trending" },
        ],
      },
      {
        items: [
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

  function flatNav(role) {
    const sections = NAV[role] || NAV.member;
    const out = [];
    sections.forEach((s) => s.items.forEach((i) => out.push(i)));
    return out;
  }

  function isActive(href, activePath) {
    if (href === activePath) return true;
    // treat a nested path as "active" for its nearest parent nav item,
    // but never let the bare overview item ("/admin", "/app") light up
    // for every sub-route.
    if (href === "/admin" || href === "/app") return false;
    return activePath.indexOf(href + "/") === 0;
  }

  function renderNav(role, activePath) {
    const sections = NAV[role] || NAV.member;
    return sections
      .map((section) => {
        const label = section.label
          ? `<div class="shell-nav-section-label">${escapeHtml(section.label)}</div>`
          : "";
        const items = section.items
          .map((item) => {
            const active = isActive(item.href, activePath) ? " is-active" : "";
            return `<a class="shell-nav-item${active}" href="${item.href}">${icon(item.icon)}<span class="shell-nav-label">${escapeHtml(item.label)}</span></a>`;
          })
          .join("");
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
    document.body.classList.add("has-shell");

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
      </aside>
      <div class="shell-body">
        <header class="shell-topbar">
          <button class="shell-mobile-toggle" id="shell-mobile-toggle" type="button" aria-label="Open navigation">
            ${ICONS.menu}
          </button>
          <nav class="shell-breadcrumbs" aria-label="Breadcrumb">${renderBreadcrumbs(breadcrumbs)}</nav>
          <div class="shell-topbar-spacer"></div>
          <button class="shell-search-btn" id="shell-search-btn" type="button">
            ${ICONS.search}<span>Search…</span><kbd>&#8984;K</kbd>
          </button>
          <button class="shell-icon-btn" id="shell-notif-btn" type="button" aria-label="Notifications">
            ${ICONS.bell}${notificationCount > 0 ? '<span class="shell-notif-dot"></span>' : ""}
          </button>
          <div class="shell-user-menu">
            <button class="shell-user-btn" id="shell-user-btn" type="button" aria-haspopup="true" aria-expanded="false">
              <span class="shell-avatar">${escapeHtml(initials(user.name))}</span>
              <span class="shell-user-name">${escapeHtml(user.name)}</span>
              ${ICONS.chevronDown}
            </button>
            <div class="dropdown-menu shell-user-dropdown" id="shell-user-dropdown" hidden>
              <div class="shell-user-dropdown-header">
                <div class="shell-user-dropdown-name">${escapeHtml(user.name)}</div>
                <div class="shell-user-dropdown-role">${user.is_admin ? "Administrator" : "Team member"}</div>
              </div>
              <a class="dropdown-item" href="/change-password">Change password</a>
              <button class="dropdown-item" id="shell-logout-btn" type="button">Log out</button>
            </div>
          </div>
        </header>
        <main class="shell-main" id="shell-main" tabindex="-1"></main>
      </div>
      <div class="shell-command-overlay" id="shell-command-overlay" hidden>
        <div class="shell-command-palette" role="dialog" aria-label="Jump to">
          <input class="shell-command-input" id="shell-command-input" type="text" placeholder="Jump to…" aria-label="Jump to a page" autocomplete="off">
          <div class="shell-command-results" id="shell-command-results"></div>
        </div>
      </div>
    `;

    document.body.appendChild(shell);
    const main = shell.querySelector("#shell-main");
    pageContent.hidden = false;
    main.appendChild(pageContent);

    wireEvents(shell, role);
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
      shell.classList.toggle("is-mobile-open");
    });
    shell.querySelectorAll(".shell-nav-item").forEach((el) => {
      el.addEventListener("click", () => shell.classList.remove("is-mobile-open"));
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

    // Command palette
    const overlay = shell.querySelector("#shell-command-overlay");
    const input = shell.querySelector("#shell-command-input");
    const results = shell.querySelector("#shell-command-results");
    const items = flatNav(role);

    function renderResults(query) {
      const q = query.trim().toLowerCase();
      const filtered = q ? items.filter((i) => i.label.toLowerCase().includes(q)) : items;
      if (!filtered.length) {
        results.innerHTML = '<div class="shell-command-empty">No matches</div>';
        return;
      }
      results.innerHTML = filtered
        .map(
          (i, idx) =>
            `<div class="shell-command-result${idx === 0 ? " is-active" : ""}" data-href="${i.href}">${icon(i.icon)}<span>${escapeHtml(i.label)}</span></div>`
        )
        .join("");
    }

    function openPalette() {
      overlay.hidden = false;
      input.value = "";
      renderResults("");
      input.focus();
    }
    function closePalette() {
      overlay.hidden = true;
    }

    shell.querySelector("#shell-search-btn").addEventListener("click", openPalette);
    document.addEventListener("keydown", (e) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        overlay.hidden ? openPalette() : closePalette();
      } else if (e.key === "Escape" && !overlay.hidden) {
        closePalette();
      }
    });
    overlay.addEventListener("click", (e) => {
      if (e.target === overlay) closePalette();
    });
    input.addEventListener("input", () => renderResults(input.value));
    results.addEventListener("click", (e) => {
      const row = e.target.closest(".shell-command-result");
      if (row && row.dataset.href) window.location.href = row.dataset.href;
    });
    input.addEventListener("keydown", (e) => {
      const rows = Array.from(results.querySelectorAll(".shell-command-result"));
      if (!rows.length) return;
      const activeIdx = rows.findIndex((r) => r.classList.contains("is-active"));
      if (e.key === "ArrowDown" || e.key === "ArrowUp") {
        e.preventDefault();
        const dir = e.key === "ArrowDown" ? 1 : -1;
        const nextIdx = (activeIdx + dir + rows.length) % rows.length;
        rows.forEach((r) => r.classList.remove("is-active"));
        rows[nextIdx].classList.add("is-active");
        rows[nextIdx].scrollIntoView({ block: "nearest" });
      } else if (e.key === "Enter") {
        const active = rows[activeIdx] || rows[0];
        if (active) window.location.href = active.dataset.href;
      }
    });
  }

  return { mount, ICONS, icon, escapeHtml, initials };
})();
