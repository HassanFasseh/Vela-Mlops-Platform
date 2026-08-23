/*
 * Vela settings — shared by /admin/settings and /app/settings. Displays
 * account info from the already-fetched /auth/me user object and wires
 * the change-password form to POST /auth/change-password.
 *
 * Note: that endpoint only requires a valid JWT — it does not verify the
 * caller's current password before setting a new one (see
 * backend/app/services/auth.py:change_password). This page is built
 * faithfully against that real contract; it isn't this page's place to
 * silently add a check the backend doesn't enforce.
 */

const Settings = (() => {
  function start(user) {
    document.getElementById("acc-username").textContent = user.username;
    document.getElementById("acc-name").textContent = user.name;
    document.getElementById("acc-role").innerHTML = UI.badge(
      user.is_admin ? "Administrator" : "Team member",
      user.is_admin ? "info" : "neutral"
    );

    const form = document.getElementById("pw-form");
    const errorEl = document.getElementById("s-error");
    const submitBtn = document.getElementById("s-submit");

    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      errorEl.textContent = "";
      const pw = document.getElementById("s-new-password").value;
      const confirm = document.getElementById("s-confirm-password").value;
      if (pw.length < 8) {
        errorEl.textContent = "Password must be at least 8 characters.";
        return;
      }
      if (pw !== confirm) {
        errorEl.textContent = "Passwords do not match.";
        return;
      }
      submitBtn.disabled = true;
      submitBtn.textContent = "Saving…";
      try {
        await Api.post("/auth/change-password", { new_password: pw });
        UI.toast("Password updated", "success");
        form.reset();
      } catch (err) {
        errorEl.textContent = err.message || "Could not update password.";
      } finally {
        submitBtn.disabled = false;
        submitBtn.textContent = "Update password";
      }
    });
  }

  return { start };
})();
