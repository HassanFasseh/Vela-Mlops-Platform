/*
 * Vela API helper — shared token storage + fetch wrapper.
 * Preserves the existing auth contract: JWT in localStorage under
 * "aodp_token", sent as "Authorization: Bearer <token>" (see CLAUDE.md).
 */

const Api = (() => {
  const TOKEN_KEY = "aodp_token";

  function getToken() {
    try {
      return localStorage.getItem(TOKEN_KEY);
    } catch (e) {
      return null;
    }
  }

  function setToken(token) {
    try {
      localStorage.setItem(TOKEN_KEY, token);
    } catch (e) {
      /* storage unavailable — auth simply won't persist across reloads */
    }
  }

  function clearToken() {
    try {
      localStorage.removeItem(TOKEN_KEY);
    } catch (e) {}
  }

  function isAuthed() {
    return !!getToken();
  }

  function goLogin() {
    if (!location.pathname.startsWith("/login")) {
      window.location.href = "/login";
    }
  }

  /**
   * Low-level request wrapper. Attaches the bearer token, JSON-encodes
   * plain-object bodies, and centralizes the two auth failure paths every
   * page needs to handle:
   *   - 401  -> token invalid/expired, send the user to /login
   *   - 403 + X-Force-Password-Change -> send the user to /change-password
   */
  async function request(path, opts = {}) {
    const headers = Object.assign({}, opts.headers);
    const isForm = typeof FormData !== "undefined" && opts.body instanceof FormData;
    if (!isForm && opts.body && typeof opts.body !== "string") {
      opts = Object.assign({}, opts, { body: JSON.stringify(opts.body) });
    }
    if (!isForm && !headers["Content-Type"] && opts.body) {
      headers["Content-Type"] = "application/json";
    }
    const token = getToken();
    if (token) headers["Authorization"] = "Bearer " + token;

    let res;
    try {
      res = await fetch(path, Object.assign({}, opts, { headers }));
    } catch (e) {
      const err = new Error("Network error — is the API reachable?");
      err.network = true;
      throw err;
    }

    if (res.status === 403 && res.headers.get("X-Force-Password-Change") === "true") {
      if (!location.pathname.startsWith("/change-password")) {
        window.location.href = "/change-password";
      }
      const err = new Error("Password change required");
      err.status = 403;
      err.forcePasswordChange = true;
      throw err;
    }

    if (res.status === 401) {
      clearToken();
      goLogin();
      const err = new Error("Not authenticated");
      err.status = 401;
      throw err;
    }

    let data = null;
    const text = await res.text();
    if (text) {
      try {
        data = JSON.parse(text);
      } catch (e) {
        data = text;
      }
    }

    if (!res.ok) {
      const detail = (data && data.detail) || res.statusText || "Request failed";
      const err = new Error(detail);
      err.status = res.status;
      err.data = data;
      throw err;
    }

    return data;
  }

  const get = (path) => request(path);
  const post = (path, body) => request(path, { method: "POST", body });
  const patch = (path, body) => request(path, { method: "PATCH", body });
  const del = (path) => request(path, { method: "DELETE" });

  async function me() {
    return get("/auth/me");
  }

  /**
   * Gate for pages that require an authenticated, non-force-change user.
   * Redirects to /login or /change-password as needed and returns null in
   * those cases so the caller can bail out of its own render.
   */
  async function requireAuth() {
    if (!isAuthed()) {
      goLogin();
      return null;
    }
    try {
      const user = await me();
      if (user.force_password_change && !location.pathname.startsWith("/change-password")) {
        window.location.href = "/change-password";
        return null;
      }
      return user;
    } catch (e) {
      return null;
    }
  }

  function logout() {
    clearToken();
    window.location.href = "/login";
  }

  return {
    TOKEN_KEY,
    getToken,
    setToken,
    clearToken,
    isAuthed,
    request,
    get,
    post,
    patch,
    del,
    me,
    requireAuth,
    logout,
  };
})();
