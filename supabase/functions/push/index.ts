// Speicherpunkt: verschickt fällige Erinnerungen als Mitteilung (Web Push). Supabase Edge Function «push».
// Wird alle 5 Minuten von der Datenbank aufgerufen (sp_push_tick in supabase-setup.sql) und bekommt einen Einmal-Code.
// Nur mit diesem Code gibt die Datenbank die fälligen Erinnerungen heraus. Es braucht keine Secrets.
// Wichtig: In den Einstellungen dieser Funktion «Verify JWT» ausschalten.
// Der Code ist reines JavaScript (ohne Typangaben), damit die Tests ihn auch unter Node ausführen können.

const PUBLIC_KEY = "sb_publishable_U214RD6vhA1GlMfMPG04Xw_Z2g_qF3l"; // öffentlicher Schlüssel, steht auch in index.html
const SUBJECT = "mailto:michael.zbinden@me.com"; // Kontakt für die Mitteilungsdienste (steht auch im Impressum)
// Nur an bekannte Mitteilungsdienste senden (Chrome/Edge/Android, Apple, Firefox, Windows).
const HOSTS = [/^fcm\.googleapis\.com$/, /\.push\.apple\.com$/, /\.push\.services\.mozilla\.com$/, /\.notify\.windows\.com$/];
const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const enc = new TextEncoder();

function reply(status, obj) {
  return new Response(JSON.stringify(obj), { status, headers: { "Content-Type": "application/json; charset=utf-8", "Cache-Control": "no-store" } });
}
function b64u(bytes) {
  let s = ""; for (const b of new Uint8Array(bytes)) s += String.fromCharCode(b);
  return btoa(s).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}
function b64ud(str) {
  const s = atob(String(str).replace(/-/g, "+").replace(/_/g, "/")); const out = new Uint8Array(s.length);
  for (let i = 0; i < s.length; i++) out[i] = s.charCodeAt(i);
  return out;
}
function concat(...parts) {
  const out = new Uint8Array(parts.reduce((n, p) => n + p.length, 0)); let o = 0;
  for (const p of parts) { out.set(p, o); o += p.length; }
  return out;
}

// ---------- Datenbank ----------
async function rpc(name, args) {
  const base = (Deno.env.get("SUPABASE_URL") || "").replace(/\/+$/, "");
  const r = await fetch(base + "/rest/v1/rpc/" + name, {
    method: "POST", headers: { apikey: Deno.env.get("SP_PUBLIC_KEY") || PUBLIC_KEY, "Content-Type": "application/json" },
    body: JSON.stringify(args), signal: AbortSignal.timeout(10000),
  });
  if (!r.ok) { const e = new Error("rpc " + name + " " + r.status); e.status = r.status; throw e; }
  return r.json();
}

// ---------- Schlüssel und Ausweis gegenüber dem Mitteilungsdienst (VAPID, RFC 8292) ----------
async function newKeys() {
  const kp = await crypto.subtle.generateKey({ name: "ECDSA", namedCurve: "P-256" }, true, ["sign", "verify"]);
  const pub = new Uint8Array(await crypto.subtle.exportKey("raw", kp.publicKey));
  const j = await crypto.subtle.exportKey("jwk", kp.privateKey);
  return { pub: b64u(pub), priv: JSON.stringify({ kty: "EC", crv: "P-256", x: j.x, y: j.y, d: j.d }) };
}
async function vapid(endpoint, keys) {
  const key = await crypto.subtle.importKey("jwk", JSON.parse(keys.priv), { name: "ECDSA", namedCurve: "P-256" }, false, ["sign"]);
  const head = b64u(enc.encode(JSON.stringify({ typ: "JWT", alg: "ES256" })));
  const body = b64u(enc.encode(JSON.stringify({ aud: new URL(endpoint).origin, exp: Math.floor(Date.now() / 1000) + 12 * 3600, sub: SUBJECT })));
  const sig = await crypto.subtle.sign({ name: "ECDSA", hash: "SHA-256" }, key, enc.encode(head + "." + body));
  return "vapid t=" + head + "." + body + "." + b64u(sig) + ", k=" + keys.pub;
}

// ---------- Verschlüsselung der Mitteilung (RFC 8291, aes128gcm) ----------
async function hkdf(salt, ikm, info, len) {
  const key = await crypto.subtle.importKey("raw", ikm, "HKDF", false, ["deriveBits"]);
  return new Uint8Array(await crypto.subtle.deriveBits({ name: "HKDF", hash: "SHA-256", salt, info }, key, len * 8));
}
async function encrypt(sub, plain) {
  const uaPub = b64ud(sub.p256dh), authSecret = b64ud(sub.auth);
  if (uaPub.length !== 65 || authSecret.length !== 16) throw new Error("subscription");
  const as = await crypto.subtle.generateKey({ name: "ECDH", namedCurve: "P-256" }, true, ["deriveBits"]);
  const asPub = new Uint8Array(await crypto.subtle.exportKey("raw", as.publicKey));
  const uaKey = await crypto.subtle.importKey("raw", uaPub, { name: "ECDH", namedCurve: "P-256" }, false, []);
  const secret = new Uint8Array(await crypto.subtle.deriveBits({ name: "ECDH", public: uaKey }, as.privateKey, 256));
  const ikm = await hkdf(authSecret, secret, concat(enc.encode("WebPush: info\0"), uaPub, asPub), 32);
  const salt = crypto.getRandomValues(new Uint8Array(16));
  const cek = await hkdf(salt, ikm, enc.encode("Content-Encoding: aes128gcm\0"), 16);
  const nonce = await hkdf(salt, ikm, enc.encode("Content-Encoding: nonce\0"), 12);
  const aes = await crypto.subtle.importKey("raw", cek, "AES-GCM", false, ["encrypt"]);
  const cipher = new Uint8Array(await crypto.subtle.encrypt({ name: "AES-GCM", iv: nonce }, aes, concat(plain, new Uint8Array([2]))));
  return concat(salt, new Uint8Array([0, 0, 16, 0]), new Uint8Array([asPub.length]), asPub, cipher);
}

// "ok" | "gone" (Gerät abgemeldet) | "failed" (später nochmals)
async function send(item, keys) {
  let host;
  try { const u = new URL(item.endpoint); if (u.protocol !== "https:") return "gone"; host = u.hostname; } catch { return "gone"; }
  if (!HOSTS.some(re => re.test(host))) return "gone";
  let body;
  try {
    const text = { t: String(item.name || "Speicherpunkt").slice(0, 80), b: item.text ? String(item.text).slice(0, 220) : item.next ? "Nächster Schritt: " + String(item.next).slice(0, 200) : "Dein nächster Schritt wartet.", p: item.project || "" };
    body = await encrypt(item, enc.encode(JSON.stringify(text)));
  } catch { return "gone"; }
  try {
    const r = await fetch(item.endpoint, {
      method: "POST", body, signal: AbortSignal.timeout(10000),
      headers: { Authorization: await vapid(item.endpoint, keys), "Content-Encoding": "aes128gcm", "Content-Type": "application/octet-stream", TTL: "86400", Urgency: "normal" },
    });
    if (r.status >= 200 && r.status < 300) return "ok";
    if (r.status === 404 || r.status === 410) return "gone";
    console.error("push " + host + " " + r.status);
    return "failed";
  } catch { return "failed"; }
}

async function handle(req) {
  if (req.method === "GET") return reply(200, { dienst: "speicherpunkt-push" });
  if (req.method !== "POST") return reply(405, { fehler: "Nur POST." });
  let nonce;
  try { nonce = (await req.json()).nonce; } catch { nonce = null; }
  if (typeof nonce !== "string" || !UUID_RE.test(nonce)) return reply(401, { fehler: "Kein gültiger Einmal-Code." });
  try {
    const claim = await rpc("sp_push_claim", { p_nonce: nonce });
    if (claim.status !== 200) return reply(401, { fehler: "Kein gültiger Einmal-Code." });
    if (!claim.keys) {
      const made = await newKeys();
      const set = await rpc("sp_push_setkeys", { p_nonce: nonce, p_pub: made.pub, p_priv: made.priv });
      return reply(set.status === 200 ? 200 : 500, { schluessel: set.status === 200 ? "angelegt" : "fehler", gesendet: 0 });
    }
    const due = Array.isArray(claim.due) ? claim.due : [];
    const gone = [], failed = []; let ok = 0;
    for (let i = 0; i < due.length; i += 10) {
      const part = due.slice(i, i + 10);
      const res = await Promise.all(part.map(it => send(it, claim.keys)));
      res.forEach((r, k) => {
        if (r === "ok") ok++;
        else if (r === "gone") gone.push(part[k].sub);
        else failed.push({ sub: part[k].sub, project: part[k].project, remind: part[k].remind });
      });
    }
    if (gone.length || failed.length) await rpc("sp_push_report", { p_nonce: nonce, p_gone: [...new Set(gone)], p_failed: failed });
    return reply(200, { gesendet: ok, entfernt: new Set(gone).size, fehlgeschlagen: failed.length });
  } catch (e) {
    console.error(e);
    return reply(e && e.status === 404 ? 500 : 503, { fehler: e && e.status === 404 ? "supabase-setup.sql ist noch nicht ausgeführt." : "Datenbank nicht erreichbar." });
  }
}

Deno.serve(handle);
