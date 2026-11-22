// Tests der Edge Function «push» unter Node. Entschlüsselt wird hier unabhängig mit node:crypto (RFC 8291),
// die Unterschrift (VAPID) wird mit dem öffentlichen Schlüssel geprüft.
import nc from "node:crypto";
let handler; const env = { SUPABASE_URL: "https://x.supabase.co" };
globalThis.Deno = { env: { get: k => env[k] }, serve: h => { handler = h; } };

const b64u = b => Buffer.from(b).toString("base64url"), b64ud = s => Buffer.from(s, "base64url");
function device() { // ein «Browser» mit eigenem Schlüsselpaar
  const ecdh = nc.createECDH("prime256v1"); ecdh.generateKeys(); const auth = nc.randomBytes(16);
  return { ecdh, authRaw: auth, p256dh: b64u(ecdh.getPublicKey()), auth: b64u(auth) };
}
const hmac = (k, d) => nc.createHmac("sha256", k).update(d).digest();
const hk = (salt, ikm, info, len) => hmac(hmac(salt, ikm), Buffer.concat([info, Buffer.from([1])])).subarray(0, len);
function decrypt(dev, body) {
  const salt = body.subarray(0, 16), rs = body.readUInt32BE(16), idlen = body[20], asPub = body.subarray(21, 21 + idlen), ct = body.subarray(21 + idlen);
  const secret = dev.ecdh.computeSecret(asPub);
  const ikm = hk(dev.authRaw, secret, Buffer.concat([Buffer.from("WebPush: info\0"), dev.ecdh.getPublicKey(), asPub]), 32);
  const cek = hk(salt, ikm, Buffer.from("Content-Encoding: aes128gcm\0"), 16), nonce = hk(salt, ikm, Buffer.from("Content-Encoding: nonce\0"), 12);
  const d = nc.createDecipheriv("aes-128-gcm", cek, nonce); d.setAuthTag(ct.subarray(ct.length - 16));
  const plain = Buffer.concat([d.update(ct.subarray(0, ct.length - 16)), d.final()]);
  return { rs, idlen, text: plain.subarray(0, plain.length - 1).toString("utf8"), pad: plain[plain.length - 1] };
}

const NONCE = "11111111-2222-4333-8444-555555555555";
const db = { nonce: NONCE, keys: null, due: [], reports: [], claims: 0, down: false, missing: false };
const sent = []; let pushStatus = () => 201;
globalThis.fetch = async (url, opts) => {
  url = String(url);
  if (url.includes("/rest/v1/rpc/")) {
    if (db.down) throw new TypeError("fetch failed");
    if (db.missing) return new Response("{}", { status: 404 });
    const a = JSON.parse(opts.body);
    if (opts.headers.apikey !== "sb_publishable_U214RD6vhA1GlMfMPG04Xw_Z2g_qF3l" || opts.headers.Authorization) return new Response("{}", { status: 401 });
    if (a.p_nonce !== db.nonce) return Response.json({ status: 401 });
    if (url.endsWith("sp_push_claim")) { db.claims++; return Response.json({ status: 200, keys: db.keys, due: db.keys ? db.due : [] }); }
    if (url.endsWith("sp_push_setkeys")) { if (!db.keys) db.keys = { pub: a.p_pub, priv: a.p_priv }; return Response.json({ status: 200, keys: db.keys }); }
    if (url.endsWith("sp_push_report")) { db.reports.push(a); return Response.json({ status: 200 }); }
  }
  sent.push({ url, opts });
  const s = pushStatus(url); if (s === "throw") throw new TypeError("network");
  return new Response(null, { status: s });
};
await import("./push.mjs");
const call = async (body, method = "POST") => { const r = await handler(new Request("https://x/functions/v1/push", { method, headers: { "content-type": "application/json" }, body: method === "POST" ? (typeof body === "string" ? body : JSON.stringify(body)) : undefined })); return { status: r.status, j: await r.json() }; };
const out = []; const t = (name, ok, info) => out.push((ok ? "ok  " : "FAIL") + " " + name + (ok || info === undefined ? "" : "  → " + JSON.stringify(info).slice(0, 300)));

let r = await call(null, "GET"); t("GET zeigt, dass die Funktion läuft", r.status === 200 && r.j.dienst === "speicherpunkt-push", r);
r = await call({}); t("ohne Code 401", r.status === 401 && db.claims === 0, r);
r = await call({ nonce: "abc" }); t("kaputter Code 401, keine Datenbankabfrage", r.status === 401 && db.claims === 0, r);
r = await call("{kaputt"); t("kaputtes JSON 401", r.status === 401, r);
r = await call({ nonce: "99999999-2222-4333-8444-555555555555" }); t("falscher Code 401", r.status === 401 && sent.length === 0, r);
r = await call({}, "PUT"); t("PUT 405", r.status === 405, r);

// Erster Lauf: Schlüsselpaar wird erzeugt und abgelegt
r = await call({ nonce: NONCE });
const pubRaw = db.keys && b64ud(db.keys.pub);
t("erster Lauf legt Schlüssel an", r.status === 200 && r.j.schluessel === "angelegt" && pubRaw.length === 65 && pubRaw[0] === 4 && JSON.parse(db.keys.priv).d, r);
const first = db.keys.pub; await call({ nonce: NONCE }); t("Schlüssel bleiben gleich", db.keys.pub === first);

// Versand
const A = device(), B = device(), C = device(), D = device();
db.due = [
  { sub: "s-a", endpoint: "https://fcm.googleapis.com/fcm/send/abc", p256dh: A.p256dh, auth: A.auth, project: "p1", remind: 111, name: "Steuererklärung 🌱", next: "Lohnausweis im Ordner suchen" },
  { sub: "s-b", endpoint: "https://web.push.apple.com/QAbc", p256dh: B.p256dh, auth: B.auth, project: "p2", remind: 222, name: "Gartenhaus", next: "" },
];
r = await call({ nonce: NONCE });
t("zwei Mitteilungen gesendet", r.status === 200 && r.j.gesendet === 2 && sent.length === 2 && db.reports.length === 0, r);
const s0 = sent[0], h = s0.opts.headers;
t("Kopfzeilen", h["Content-Encoding"] === "aes128gcm" && h.TTL === "86400" && s0.opts.method === "POST" && /^vapid t=[\w-]+\.[\w-]+\.[\w-]+, k=/.test(h.Authorization), h);
const d0 = decrypt(A, Buffer.from(s0.opts.body)), m0 = JSON.parse(d0.text);
t("Gerät A kann entschlüsseln (RFC 8291)", d0.rs === 4096 && d0.idlen === 65 && d0.pad === 2 && m0.t === "Steuererklärung 🌱" && m0.b === "Nächster Schritt: Lohnausweis im Ordner suchen" && m0.p === "p1", d0);
const m1 = JSON.parse(decrypt(B, Buffer.from(sent[1].opts.body)).text);
t("ohne Schritt: neutraler Text", m1.t === "Gartenhaus" && m1.b === "Dein nächster Schritt wartet." && m1.p === "p2", m1);
let wrong = false; try { decrypt(C, Buffer.from(s0.opts.body)); } catch { wrong = true; } t("fremdes Gerät kann nicht entschlüsseln", wrong);
t("jede Mitteilung anders verschlüsselt", Buffer.compare(Buffer.from(s0.opts.body).subarray(0, 16), Buffer.from(sent[1].opts.body).subarray(0, 16)) !== 0);
// VAPID prüfen
const [jh, jp, js] = h.Authorization.match(/t=([^,]+)/)[1].split("."); const claims = JSON.parse(b64ud(jp)); const k = h.Authorization.match(/k=(.+)$/)[1];
const pubKey = nc.createPublicKey({ key: { kty: "EC", crv: "P-256", x: b64u(pubRaw.subarray(1, 33)), y: b64u(pubRaw.subarray(33)) }, format: "jwk" });
t("Unterschrift gültig", nc.verify("sha256", Buffer.from(jh + "." + jp), { key: pubKey, dsaEncoding: "ieee-p1363" }, b64ud(js)) && JSON.parse(b64ud(jh)).alg === "ES256");
const now = Math.floor(Date.now() / 1000);
t("Angaben im Ausweis", claims.aud === "https://fcm.googleapis.com" && claims.sub.startsWith("mailto:") && claims.exp > now + 3600 && claims.exp <= now + 24 * 3600 && k === db.keys.pub, claims);
t("Apple bekommt eigene Adresse im Ausweis", JSON.parse(b64ud(sent[1].opts.headers.Authorization.match(/t=([^,]+)/)[1].split(".")[1])).aud === "https://web.push.apple.com");

// Fehlerfälle
sent.length = 0;
db.due = [
  { sub: "s-a", endpoint: "https://fcm.googleapis.com/fcm/send/abc", p256dh: A.p256dh, auth: A.auth, project: "p1", remind: 1, name: "A", next: "a" },
  { sub: "s-c", endpoint: "https://updates.push.services.mozilla.com/wpush/v2/x", p256dh: C.p256dh, auth: C.auth, project: "p3", remind: 3, name: "C", next: "c" },
  { sub: "s-d", endpoint: "https://db3p.notify.windows.com/w/?token=x", p256dh: D.p256dh, auth: D.auth, project: "p4", remind: 4, name: "D", next: "d" },
  { sub: "s-e", endpoint: "https://evil.example.com/steal", p256dh: D.p256dh, auth: D.auth, project: "p5", remind: 5, name: "E", next: "e" },
  { sub: "s-f", endpoint: "http://fcm.googleapis.com/x", p256dh: D.p256dh, auth: D.auth, project: "p6", remind: 6, name: "F", next: "f" },
  { sub: "s-g", endpoint: "https://fcm.googleapis.com/fcm/send/g", p256dh: "kaputt", auth: "x", project: "p7", remind: 7, name: "G", next: "g" },
  { sub: "s-h", endpoint: "https://fcm.googleapis.com/fcm/send/h", p256dh: B.p256dh, auth: B.auth, project: "p8", remind: 8, name: "H", next: "h" },
];
pushStatus = url => url.includes("mozilla") ? 410 : url.includes("windows") ? 503 : url.endsWith("/h") ? "throw" : 201;
r = await call({ nonce: NONCE }); const rep = db.reports[0] || {};
t("Zählung: 1 gesendet, 4 entfernt, 2 fehlgeschlagen", r.j.gesendet === 1 && r.j.entfernt === 4 && r.j.fehlgeschlagen === 2, r.j);
t("abgemeldete, fremde, unverschlüsselte und kaputte Geräte gemeldet", JSON.stringify([...rep.p_gone].sort()) === JSON.stringify(["s-c", "s-e", "s-f", "s-g"]), rep);
t("Fehlgeschlagenes wird zum Wiederholen gemeldet", JSON.stringify(rep.p_failed) === JSON.stringify([{ sub: "s-d", project: "p4", remind: 4 }, { sub: "s-h", project: "p8", remind: 8 }]), rep);
t("nie an fremde Adressen gesendet", !sent.some(s => s.url.includes("evil") || s.url.startsWith("http://")), sent.map(s => s.url));
pushStatus = () => 201; sent.length = 0; db.reports.length = 0;
db.due = [{ sub: "s-a", endpoint: "https://fcm.googleapis.com/fcm/send/abc", p256dh: A.p256dh, auth: A.auth, project: "", remind: 0, name: "Speicherpunkt", text: "Das ist eine Probe." }];
r = await call({ nonce: NONCE }); const probe = JSON.parse(decrypt(A, Buffer.from(sent[0].opts.body)).text);
t("Probe-Mitteilung", r.j.gesendet === 1 && probe.t === "Speicherpunkt" && probe.b === "Das ist eine Probe." && probe.p === "", probe);
db.due = Array.from({ length: 25 }, (_, i) => ({ sub: "s" + i, endpoint: "https://fcm.googleapis.com/fcm/send/" + i, p256dh: A.p256dh, auth: A.auth, project: "p" + i, remind: i, name: "x".repeat(300), next: "y".repeat(900) }));
sent.length = 0; r = await call({ nonce: NONCE }); const big = JSON.parse(decrypt(A, Buffer.from(sent[0].opts.body)).text);
t("25 auf einmal, lange Texte gekürzt, passt in einen Block", r.j.gesendet === 25 && big.t.length === 80 && big.b.length <= 220 && sent[0].opts.body.length < 4096, [r.j, sent[0].opts.body.length]);
db.down = true; r = await call({ nonce: NONCE }); t("Datenbank weg → 503", r.status === 503, r); db.down = false;
db.missing = true; r = await call({ nonce: NONCE }); t("SQL fehlt → 500 mit Hinweis", r.status === 500 && r.j.fehler.includes("supabase-setup.sql"), r); db.missing = false;

console.log(out.join("\n"));
console.log(out.some(x => x.startsWith("FAIL")) ? "SOME FAILED" : "ALL OK (" + out.length + ")");
