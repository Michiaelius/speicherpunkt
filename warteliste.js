// Warteliste: trägt E-Mail und freiwillige Antwort in die Supabase-Tabelle sp_waitlist ein.
(() => {
  "use strict";
  const CFG = window.SP_CONFIG || {
    url: "https://satqwruqmwgcflcggbul.supabase.co",
    key: "sb_publishable_U214RD6vhA1GlMfMPG04Xw_Z2g_qF3l"
  };
  const form = document.getElementById("wl-form");
  if (!form) return;
  const email = form.querySelector("#wl-email"), note = form.querySelector("#wl-note"), trap = form.querySelector("#wl-website");
  const btn = form.querySelector("#wl-submit"), status = form.querySelector("#wl-status");

  function say(text, kind) { status.textContent = text; status.className = "wl-status" + (kind ? " " + kind : ""); }
  function done(text) { form.classList.add("done"); say(text, "ok"); }

  email.addEventListener("input", () => email.removeAttribute("aria-invalid"));
  form.addEventListener("submit", async e => {
    e.preventDefault();
    if (trap.value) { done("Danke, du bist eingetragen."); return; }   // Spam-Schutz: Menschen sehen dieses Feld nicht
    const mail = email.value.trim().toLowerCase();
    if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(mail) || mail.length > 254) {
      email.setAttribute("aria-invalid", "true"); email.focus();
      say("Gib eine gültige E-Mail-Adresse ein.", "err"); return;
    }
    const source = (new URLSearchParams(location.search).get("q") || "willkommen").replace(/[^\w-]/g, "").slice(0, 50) || "willkommen";
    btn.disabled = true; say("Wird eingetragen …");
    try {
      const r = await fetch(CFG.url.replace(/\/+$/, "") + "/rest/v1/sp_waitlist", {
        method: "POST",
        headers: { apikey: CFG.key, "Content-Type": "application/json", Prefer: "return=minimal" },
        body: JSON.stringify({ email: mail, note: note.value.trim().slice(0, 1000) || null, source })
      });
      if (r.ok) done("Danke, du bist eingetragen. Wir melden uns, sobald es Neues gibt.");
      else if (r.status === 409) done("Du bist schon auf der Warteliste. Danke!");
      else { btn.disabled = false; say("Das hat nicht geklappt. Versuch es bitte später nochmals.", "err"); }
    } catch {
      btn.disabled = false; say("Keine Verbindung. Prüf dein Internet und versuch es nochmals.", "err");
    }
  });
})();
