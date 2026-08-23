/*
 * Vela shared UI helpers used across admin/member pages: modals, toasts,
 * badges, and small formatters. Depends on components.css classes and
 * (for escapeHtml) falls back to its own copy if shell.js isn't loaded.
 */

const UI = (() => {
  function escapeHtml(str) {
    if (window.Shell && Shell.escapeHtml) return Shell.escapeHtml(str);
    return String(str == null ? "" : str).replace(/[&<>"']/g, (c) => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
    }[c]));
  }

  /* ---- Toasts --------------------------------------------------------*/
  function toastStack() {
    let stack = document.querySelector(".toast-stack");
    if (!stack) {
      stack = document.createElement("div");
      stack.className = "toast-stack";
      stack.setAttribute("role", "status");
      stack.setAttribute("aria-live", "polite");
      document.body.appendChild(stack);
    }
    return stack;
  }

  function toast(message, variant = "info", timeout = 4000) {
    const stack = toastStack();
    const el = document.createElement("div");
    el.className = `toast toast-${variant}`;
    el.textContent = message;
    stack.appendChild(el);
    setTimeout(() => el.remove(), timeout);
  }

  /* ---- Modal -----------------------------------------------------------*/
  const FOCUSABLE_SELECTOR =
    'a[href], button:not([disabled]), input:not([disabled]):not([type="hidden"]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';

  let modalReturnFocusEl = null;

  function openModal({ title, bodyHtml, footerHtml }) {
    closeModal();
    modalReturnFocusEl = document.activeElement;

    const overlay = document.createElement("div");
    overlay.className = "modal-overlay";
    overlay.id = "ui-modal-overlay";
    overlay.innerHTML = `
      <div class="modal" role="dialog" aria-modal="true" aria-label="${escapeHtml(title || "")}">
        <div class="modal-header">
          <div class="modal-title">${escapeHtml(title || "")}</div>
          <button class="btn btn-ghost btn-sm" id="ui-modal-close" type="button" aria-label="Close">&#10005;</button>
        </div>
        <div class="modal-body">${bodyHtml || ""}</div>
        ${footerHtml ? `<div class="modal-footer">${footerHtml}</div>` : ""}
      </div>
    `;
    document.body.appendChild(overlay);
    overlay.querySelector("#ui-modal-close").addEventListener("click", closeModal);
    overlay.addEventListener("click", (e) => {
      if (e.target === overlay) closeModal();
    });
    document.addEventListener("keydown", modalKeyHandler);

    // Initial focus: first real input if there is one, else the close button —
    // never leave focus stranded on whatever was behind the modal.
    const dialog = overlay.querySelector(".modal");
    const focusable = dialog.querySelectorAll(FOCUSABLE_SELECTOR);
    const firstField = dialog.querySelector("input:not([type=hidden]), textarea, select");
    (firstField || focusable[0] || dialog).focus();

    return overlay;
  }

  function modalKeyHandler(e) {
    if (e.key === "Escape") {
      closeModal();
      return;
    }
    if (e.key !== "Tab") return;
    const overlay = document.getElementById("ui-modal-overlay");
    if (!overlay) return;
    const dialog = overlay.querySelector(".modal");
    const focusable = Array.from(dialog.querySelectorAll(FOCUSABLE_SELECTOR)).filter((el) => el.offsetParent !== null);
    if (!focusable.length) return;
    const first = focusable[0];
    const last = focusable[focusable.length - 1];
    // Focus trap (WCAG 2.4.3): Tab/Shift+Tab cycles within the dialog
    // instead of escaping to the page behind it.
    if (e.shiftKey && document.activeElement === first) {
      e.preventDefault();
      last.focus();
    } else if (!e.shiftKey && document.activeElement === last) {
      e.preventDefault();
      first.focus();
    }
  }

  function closeModal() {
    const existing = document.getElementById("ui-modal-overlay");
    if (existing) existing.remove();
    document.removeEventListener("keydown", modalKeyHandler);
    if (modalReturnFocusEl && document.contains(modalReturnFocusEl)) {
      modalReturnFocusEl.focus();
    }
    modalReturnFocusEl = null;
  }

  /* ---- Badges ----------------------------------------------------------*/
  const STATUS_VARIANT = {
    online: "success", running: "success", healthy: "success", active: "success",
    starting: "warning", pending: "warning", uploaded: "warning", investigating: "warning",
    offline: "danger", failed: "danger", critical: "danger",
    open: "info", closed: "neutral", inactive: "neutral", resolved: "success",
  };

  const SEVERITY_VARIANT = { low: "neutral", medium: "info", high: "warning", critical: "danger" };

  function badge(label, variant = "neutral", withDot = false) {
    const dot = withDot ? '<span class="badge-dot"></span>' : "";
    return `<span class="badge badge-${variant}">${dot}${escapeHtml(label)}</span>`;
  }

  function statusBadge(status) {
    const s = String(status || "unknown").toLowerCase();
    const variant = STATUS_VARIANT[s] || "neutral";
    return badge(s.charAt(0).toUpperCase() + s.slice(1), variant, true);
  }

  function severityBadge(sev) {
    const s = String(sev || "medium").toLowerCase();
    return badge(s.charAt(0).toUpperCase() + s.slice(1), SEVERITY_VARIANT[s] || "info");
  }

  /* ---- Formatters --------------------------------------------------------*/
  function fmtDate(value) {
    if (!value) return "—";
    const d = new Date(value.endsWith ? (value.endsWith("Z") ? value : value + "Z") : value);
    if (isNaN(d.getTime())) return "—";
    return d.toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
  }

  function timeAgo(value) {
    if (!value) return "—";
    const d = new Date(value.endsWith ? (value.endsWith("Z") ? value : value + "Z") : value);
    if (isNaN(d.getTime())) return "—";
    const seconds = Math.max(0, (Date.now() - d.getTime()) / 1000);
    if (seconds < 60) return "just now";
    const mins = Math.floor(seconds / 60);
    if (mins < 60) return mins + "m ago";
    const hours = Math.floor(mins / 60);
    if (hours < 24) return hours + "h ago";
    const days = Math.floor(hours / 24);
    if (days < 30) return days + "d ago";
    return fmtDate(value);
  }

  function skeletonRows(cols, rows = 3) {
    return Array.from({ length: rows })
      .map(
        () =>
          `<tr>${Array.from({ length: cols })
            .map(() => `<td><span class="skeleton skeleton-text">&nbsp;</span></td>`)
            .join("")}</tr>`
      )
      .join("");
  }

  function emptyState(title, body, iconSvg) {
    return `
      <div class="empty-state">
        ${iconSvg ? `<div class="empty-state-icon">${iconSvg}</div>` : ""}
        <div class="empty-state-title">${escapeHtml(title)}</div>
        <div class="empty-state-body">${escapeHtml(body)}</div>
      </div>`;
  }

  function errorState(message, onRetry) {
    const id = "err-retry-" + Math.random().toString(36).slice(2, 8);
    setTimeout(() => {
      const btn = document.getElementById(id);
      if (btn && onRetry) btn.addEventListener("click", onRetry);
    }, 0);
    return `
      <div class="error-state">
        <div class="error-state-title">Something went wrong</div>
        <div class="error-state-body">${escapeHtml(message)}</div>
        ${onRetry ? `<button class="btn btn-secondary btn-sm" id="${id}" type="button" style="margin-top:.5rem">Retry</button>` : ""}
      </div>`;
  }

  return {
    escapeHtml, toast, openModal, closeModal,
    badge, statusBadge, severityBadge,
    fmtDate, timeAgo, skeletonRows, emptyState, errorState,
  };
})();
