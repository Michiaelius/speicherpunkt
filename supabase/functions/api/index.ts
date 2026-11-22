// Speicherpunkt: Schnittstelle für andere Programme, zum Beispiel ZbiWeb (Supabase Edge Function «api»).
// Aufruf: https://<projekt>.supabase.co/functions/v1/api/projekte  mit dem Header  Authorization: Bearer sp_…
// Den Token erzeugt man in der App unter Einstellungen → Schnittstelle. Beschreibung: SCHNITTSTELLE.md.
// Wichtig: In den Einstellungen dieser Funktion «Verify JWT» ausschalten. Der Token wird hier selbst geprüft.
// Der Code ist reines JavaScript (ohne Typangaben), damit die Tests ihn auch unter Node ausführen können.

const PUBLIC_KEY = "sb_publishable_U214RD6vhA1GlMfMPG04Xw_Z2g_qF3l"; // öffentlicher Schlüssel, steht auch in index.html
const VERSION = 2;
const MAX = { name: 80, wo: 1000, schritt: 200, body: 65536, suche: 200, limit: 100 };
const TOKEN_RE = /^sp_[0-9a-f]{64}$/;
const DAY = 86400000;

// ---------- Antworten ----------
function reply(status, obj, extra) {
  const headers = { "Cache-Control": "no-store", ...(extra || {}) };
  if (obj === undefined) return new Response(null, { status, headers });
  return new Response(JSON.stringify(obj), { status, headers: { "Content-Type": "application/json; charset=utf-8", ...headers } });
}
function fehler(status, text, extra, more) { return reply(status, { fehler: text, ...(more || {}) }, extra); }
class Fehler extends Error { constructor(status, text, more) { super(text); this.status = status; this.more = more; } }

// ---------- Datenbank (über die Funktionen in supabase-setup.sql) ----------
function base() { return (Deno.env.get("SUPABASE_URL") || "").replace(/\/+$/, ""); }
async function rpc(name, args) {
  let r;
  try {
    r = await fetch(base() + "/rest/v1/rpc/" + name, {
      method: "POST",
      headers: { apikey: Deno.env.get("SP_PUBLIC_KEY") || PUBLIC_KEY, "Content-Type": "application/json" },
      body: JSON.stringify(args),
      signal: AbortSignal.timeout(10000),
    });
  } catch { throw new Fehler(503, "Die Datenbank ist gerade nicht erreichbar. Bitte später nochmals versuchen."); }
  if (r.status === 404) throw new Fehler(500, "Die Schnittstelle ist noch nicht eingerichtet: supabase-setup.sql im Supabase SQL Editor ausführen.");
  if (!r.ok) throw new Fehler(500, "Fehler in der Datenbank (" + r.status + ").");
  return r.json();
}

// ---------- Hilfen ----------
const now = () => Date.now();
function num(v) { return typeof v === "number" && isFinite(v) ? v : 0; }
function iso(ms) { return ms ? new Date(ms).toISOString().replace(/\.\d{3}Z$/, "Z") : null; }
function uid() {
  const b = new Uint8Array(12); crypto.getRandomValues(b);
  return Array.from(b, x => "0123456789abcdefghijklmnopqrstuvwxyz"[x % 36]).join("");
}
function emptyState() { return { v: 2, projects: [], deleted: {}, updated: 0 }; }
// Nimmt die gespeicherten Daten so, wie die App sie ablegt, und ergänzt fehlende Teile, ohne Unbekanntes zu verlieren.
function readState(data) {
  const s = data && typeof data === "object" && !Array.isArray(data) ? data : emptyState();
  if (!Array.isArray(s.projects)) s.projects = [];
  if (!s.deleted || typeof s.deleted !== "object" || Array.isArray(s.deleted)) s.deleted = {};
  s.projects = s.projects.filter(p => p && typeof p === "object" && typeof p.id === "string" && p.id);
  for (const p of s.projects) {
    if (!Array.isArray(p.saves)) p.saves = [];
    p.saves = p.saves.filter(sv => sv && typeof sv === "object" && typeof sv.next === "string");
    if (typeof p.name !== "string" || !p.name.trim()) p.name = "Ohne Namen";
  }
  return s;
}
function current(p) { return p.saves.length ? p.saves[p.saves.length - 1] : null; }
function status(p) { return p.finished ? "fertig" : p.paused ? "ruht" : "aktiv"; }
function touched(p) { const c = current(p); return Math.max(num(p.mod), c ? num(c.at) : 0, num(p.created)); }
function due(p) { return !p.paused && !p.finished && !!p.remindAt && p.remindAt <= now(); }

function speicherpunkt(sv) {
  return { id: sv.id || null, wo: typeof sv.where === "string" ? sv.where : "", naechster_schritt: sv.next,
    erledigt: !!sv.done, erledigt_am: iso(num(sv.doneAt)), gespeichert: iso(num(sv.at)), abschluss: !!sv.final };
}
function projekt(p, full) {
  const c = current(p);
  const o = { id: p.id, name: p.name, status: status(p), faellig: due(p), erinnerung: iso(num(p.remindAt)),
    erstellt: iso(num(p.created)), geaendert: iso(touched(p)), abgeschlossen: iso(num(p.finished)),
    speicherpunkt: c ? speicherpunkt(c) : null, anzahl_speicherpunkte: p.saves.length };
  if (full) o.verlauf = p.saves.slice().reverse().map(speicherpunkt);
  return o;
}

// Prüft ein Textfeld. Fehlt es: undefined. Leer bei Pflichtfeld: 400 (beim Anlegen) bzw. 422 (beim Ändern).
function textField(body, key, max, { required = false, emptyStatus = 400, allowEmpty = false } = {}) {
  if (!(key in body) || body[key] === undefined) {
    if (required) throw new Fehler(400, key + " fehlt.");
    return undefined;
  }
  const v = body[key];
  if (typeof v !== "string") throw new Fehler(422, key + " muss Text sein.");
  const t = v.trim();
  if (!t && !allowEmpty) throw new Fehler(emptyStatus, key + " ist leer.");
  if (t.length > max) throw new Fehler(422, key + " ist zu lang (höchstens " + max + " Zeichen).");
  return t;
}
const ISO_RE = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(:\d{2}(\.\d{1,9})?)?(Z|[+-]\d{2}:\d{2})$/;
function reminderField(body) {
  if (!("erinnerung" in body) || body.erinnerung === undefined) return undefined;
  const v = body.erinnerung;
  if (v === null) return null;
  const ms = typeof v === "string" && ISO_RE.test(v) ? Date.parse(v) : NaN;
  if (!isFinite(ms) || ms < Date.UTC(2000, 0, 1) || ms > Date.UTC(2100, 0, 1))
    throw new Fehler(422, "erinnerung muss ein Zeitpunkt im Format ISO 8601 mit Zeitzone sein, zum Beispiel 2026-11-20T08:00:00+01:00, oder null.");
  return ms;
}
function boolField(body, key) {
  if (!(key in body) || body[key] === undefined) return undefined;
  if (typeof body[key] !== "boolean") throw new Fehler(422, key + " muss true oder false sein.");
  return body[key];
}
function findProject(s, id) {
  const p = s.projects.find(x => x.id === id);
  if (!p) throw new Fehler(404, "Ein Projekt mit dieser id gibt es nicht.");
  return p;
}
function touch(s, p, t) { if (p) p.mod = t; s.updated = t; }

// ---------- Endpunkte ----------
// Jeder Endpunkt bekommt die aktuellen Daten und gibt { status, body, write } zurück.
// write: true heisst, die Daten wurden verändert und müssen gespeichert werden.

function listProjects(s, q) {
  const st = (q.get("status") || "alle").trim().toLowerCase();
  if (!["alle", "aktiv", "ruht", "fertig"].includes(st)) throw new Fehler(422, "status muss alle, aktiv, ruht oder fertig sein.");
  const rawLimit = q.get("limit");
  let limit = 20;
  if (rawLimit !== null && rawLimit !== "") {
    if (!/^\d+$/.test(rawLimit.trim()) || Number(rawLimit) < 1) throw new Fehler(422, "limit muss eine ganze Zahl zwischen 1 und 100 sein.");
    limit = Math.min(MAX.limit, Number(rawLimit));
  }
  const suche = (q.get("suche") || "").trim().toLowerCase().slice(0, MAX.suche);
  const words = suche ? suche.split(/\s+/) : [];
  const hits = s.projects
    .filter(p => st === "alle" || status(p) === st)
    .filter(p => {
      if (!words.length) return true;
      const hay = [p.name, ...p.saves.map(sv => (sv.where || "") + " " + sv.next)].join(" ").toLowerCase();
      return words.every(w => hay.includes(w));
    })
    .sort((a, b) => touched(b) - touched(a))
    .slice(0, limit)
    .map(p => projekt(p, false));
  return { status: 200, body: { projekte: hits, anzahl: hits.length } };
}

function createProject(s, body, t) {
  const name = textField(body, "name", MAX.name, { required: true });
  const next = textField(body, "naechster_schritt", MAX.schritt, { required: true });
  const where = textField(body, "wo", MAX.wo, { allowEmpty: true });
  const remind = reminderField(body);
  const twin = s.projects.find(p => !p.finished && p.name.trim().toLowerCase() === name.toLowerCase());
  if (twin) throw new Fehler(409, "Es gibt schon ein offenes Projekt mit diesem Namen.", { id: twin.id });
  const p = { id: uid(), name, created: t, paused: false, finished: null, remindAt: remind || null, mod: t,
    saves: [{ id: uid(), at: t, where: where || "", next }] };
  s.projects.push(p); delete s.deleted[p.id]; touch(s, p, t);
  return { status: 201, body: projekt(p, true), write: true };
}

function changeProject(s, id, body, t) {
  const p = findProject(s, id);
  const known = ["name", "status", "erinnerung", "naechster_schritt", "abschluss_notiz"].filter(k => k in body);
  if (!known.length) throw new Fehler(400, "Kein änderbares Feld. Erlaubt sind name, status, erinnerung, naechster_schritt und abschluss_notiz.");
  const name = textField(body, "name", MAX.name, { emptyStatus: 422 });
  const next = textField(body, "naechster_schritt", MAX.schritt, { emptyStatus: 422 });
  const note = textField(body, "abschluss_notiz", MAX.wo, { emptyStatus: 422 });
  const remind = reminderField(body);
  let st;
  if ("status" in body) {
    st = typeof body.status === "string" ? body.status.trim().toLowerCase() : "";
    if (!["aktiv", "ruht", "fertig"].includes(st)) throw new Fehler(422, "status muss aktiv, ruht oder fertig sein.");
  }
  if (note !== undefined && st !== "fertig") throw new Fehler(422, "abschluss_notiz geht nur zusammen mit status fertig.");
  if (p.finished && (st === "aktiv" || st === "ruht"))
    throw new Fehler(409, "Das Projekt ist abgeschlossen. Zum Wiedereröffnen einen neuen Speicherpunkt setzen: POST /projekte/" + id + "/speicherpunkte");
  if (next !== undefined) {
    const c = current(p);
    if (!c || c.done || p.finished || st === "fertig")
      throw new Fehler(409, "Es gibt keinen offenen Schritt zum Ändern. Setz stattdessen einen neuen Speicherpunkt: POST /projekte/" + id + "/speicherpunkte");
    c.next = next;
  }
  if (name !== undefined) p.name = name;
  if (remind !== undefined) p.remindAt = remind;
  if (st === "aktiv") p.paused = false;
  if (st === "ruht") { p.paused = true; p.remindAt = null; }
  if (st === "fertig") {
    if (note) {
      const c = current(p); if (c && !c.done) { c.done = true; c.doneAt = t; }
      p.saves.push({ id: uid(), at: t, where: note, next: "Abgeschlossen", done: true, final: true });
    }
    if (!p.finished) p.finished = t;
    p.paused = false; p.remindAt = null;
  }
  touch(s, p, t);
  return { status: 200, body: projekt(p, true), write: true };
}

function deleteProject(s, id, t) {
  findProject(s, id);
  s.projects = s.projects.filter(p => p.id !== id);
  s.deleted[id] = t; touch(s, null, t);
  return { status: 204, body: undefined, write: true };
}

function addSave(s, id, body, t) {
  const p = findProject(s, id);
  const next = textField(body, "naechster_schritt", MAX.schritt, { required: true });
  const where = textField(body, "wo", MAX.wo, { allowEmpty: true });
  const doneBefore = boolField(body, "letzter_erledigt");
  const remind = reminderField(body);
  const c = current(p);
  if (doneBefore && c && !c.done) { c.done = true; c.doneAt = t; }
  p.saves.push({ id: uid(), at: t, where: where || "", next });
  p.remindAt = remind || null; p.paused = false; p.finished = null;
  touch(s, p, t);
  return { status: 201, body: projekt(p, true), write: true };
}

function listSaves(s, id) {
  const p = findProject(s, id);
  const list = p.saves.slice().reverse().map(speicherpunkt);
  return { status: 200, body: { speicherpunkte: list, anzahl: list.length } };
}

// ---------- Weiche ----------
function route(req, url) {
  let segs = url.pathname.split("/").filter(Boolean).map(x => { try { return decodeURIComponent(x); } catch { return x; } });
  const at = segs.indexOf("api");
  if (at >= 0) segs = segs.slice(at + 1);
  if (segs[0] === "v1" || segs[0] === "v2") segs = segs.slice(1);
  const m = req.method;
  if (segs.length === 0) return { allow: ["GET"], run: m === "GET" ? () => ({ status: 200, body: { schnittstelle: "speicherpunkt", version: VERSION } }) : null };
  if (segs[0] !== "projekte" || segs.length > 3) return null;
  if (segs.length === 1) return { allow: ["GET", "POST"], run: m === "GET" ? (s) => listProjects(s, url.searchParams) : m === "POST" ? (s, b, t) => createProject(s, b, t) : null, body: m === "POST" };
  const id = segs[1];
  if (segs.length === 2) return { allow: ["GET", "PATCH", "DELETE"], body: m === "PATCH",
    run: m === "GET" ? (s) => ({ status: 200, body: projekt(findProject(s, id), true) }) : m === "PATCH" ? (s, b, t) => changeProject(s, id, b, t) : m === "DELETE" ? (s, b, t) => deleteProject(s, id, t) : null };
  if (segs[2] === "speicherpunkte") return { allow: ["GET", "POST"], body: m === "POST",
    run: m === "GET" ? (s) => listSaves(s, id) : m === "POST" ? (s, b, t) => addSave(s, id, b, t) : null };
  return null;
}

async function readBody(req) {
  const len = Number(req.headers.get("content-length") || 0);
  if (len > MAX.body) throw new Fehler(413, "Der Körper ist zu gross (höchstens 64 KB).");
  const raw = await req.text();
  if (raw.length > MAX.body) throw new Fehler(413, "Der Körper ist zu gross (höchstens 64 KB).");
  if (!raw.trim()) return {};
  let b;
  try { b = JSON.parse(raw); } catch { throw new Fehler(400, "Der Körper ist kein gültiges JSON."); }
  if (!b || typeof b !== "object" || Array.isArray(b)) throw new Fehler(400, "Der Körper muss ein JSON-Objekt sein.");
  return b;
}

async function handle(req) {
  const url = new URL(req.url);
  const r = route(req, url);
  if (req.method === "OPTIONS") return reply(204, undefined, { Allow: r ? r.allow.join(", ") + ", OPTIONS" : "OPTIONS" });

  const auth = req.headers.get("authorization") || "";
  const token = auth.replace(/^Bearer\s+/i, "").trim();
  if (!auth || !/^Bearer\s+/i.test(auth) || !token) return fehler(401, "Token fehlt. Header: Authorization: Bearer <TOKEN>");
  if (!TOKEN_RE.test(token)) return fehler(401, "Token ist falsch.");

  try {
    let opened = await rpc("sp_api_open", { p_token: token, p_count: true });
    if (opened.status === 401) return fehler(401, "Token ist falsch oder wurde in der App ersetzt.");
    if (opened.status === 429) return fehler(429, "Zu viele Aufrufe. Höchstens 60 pro Minute.", { "Retry-After": String(opened.retry || 60) });
    if (opened.status !== 200) return fehler(500, "Unerwartete Antwort der Datenbank.");

    if (!r) return fehler(404, "Diesen Pfad gibt es nicht. Siehe SCHNITTSTELLE.md.");
    if (!r.run) return fehler(405, "Diese Methode geht hier nicht. Erlaubt: " + r.allow.join(", ") + ".", { Allow: r.allow.join(", ") });
    const body = r.body ? await readBody(req) : {};

    // Lesen, ändern, schreiben. Hat in der Zwischenzeit die App geschrieben (409), nochmals mit frischen Daten.
    for (let attempt = 0; attempt < 4; attempt++) {
      if (attempt > 0) {
        opened = await rpc("sp_api_open", { p_token: token, p_count: false });
        if (opened.status !== 200) return fehler(401, "Token ist falsch oder wurde in der App ersetzt.");
      }
      const s = readState(opened.data);
      const res = r.run(s, body, now());
      if (!res.write) return reply(res.status, res.body);
      const w = await rpc("sp_api_write", { p_token: token, p_rev: opened.rev === undefined ? null : opened.rev, p_data: s });
      if (w.status === 200) return reply(res.status, res.body);
      if (w.status === 401) return fehler(401, "Token ist falsch oder wurde in der App ersetzt.");
      if (w.status !== 409) return fehler(500, "Speichern hat nicht geklappt.");
    }
    return fehler(409, "Die Daten wurden gerade gleichzeitig geändert. Bitte nochmals versuchen.");
  } catch (e) {
    if (e instanceof Fehler) return fehler(e.status, e.message, undefined, e.more);
    console.error(e);
    return fehler(500, "Fehler in der Schnittstelle.");
  }
}

Deno.serve(handle);
