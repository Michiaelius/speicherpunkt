// Tests der Edge Function «api» unter Node. Die Datenbank-Funktionen sp_api_open und sp_api_write
// werden hier im Speicher nachgebaut (gleiches Verhalten wie in supabase-setup.sql).
let handler; const env = { SUPABASE_URL: "https://x.supabase.co" };
globalThis.Deno = { env: { get: k => env[k] }, serve: h => { handler = h; } };

const TOKEN = "sp_" + "a1".repeat(32), OTHER = "sp_" + "b2".repeat(32);
const db = { tokens: { [TOKEN]: "u1" }, rows: {}, hits: 0, rateRetry: 0, down: false, missing: false, conflicts: 0, onConflict: null, writes: 0, opens: 0 };
globalThis.fetch = async (url, opts) => {
  if (db.down) throw new TypeError("fetch failed");
  if (db.missing) return new Response(JSON.stringify({ code: "PGRST202" }), { status: 404 });
  const a = JSON.parse(opts.body);
  if (opts.headers.apikey !== "sb_publishable_U214RD6vhA1GlMfMPG04Xw_Z2g_qF3l") return new Response("{}", { status: 401 });
  const u = db.tokens[a.p_token];
  if (url.endsWith("/rpc/sp_api_open")) {
    db.opens++;
    if (!u) return Response.json({ status: 401 });
    if (a.p_count) { db.hits++; if (db.rateRetry) return Response.json({ status: 429, retry: db.rateRetry }); }
    const row = db.rows[u];
    return Response.json(row ? { status: 200, data: JSON.parse(JSON.stringify(row.data)), rev: row.rev } : { status: 200, data: null, rev: null });
  }
  if (url.endsWith("/rpc/sp_api_write")) {
    if (!u) return Response.json({ status: 401 });
    if (db.conflicts > 0) { db.conflicts--; if (db.onConflict) db.onConflict(); return Response.json({ status: 409 }); }
    const row = db.rows[u];
    if (a.p_rev === null) { if (row) return Response.json({ status: 409 }); db.rows[u] = { data: a.p_data, rev: 0 }; }
    else { if (!row || row.rev !== a.p_rev) return Response.json({ status: 409 }); row.data = a.p_data; row.rev++; }
    db.writes++;
    return Response.json({ status: 200, rev: db.rows[u].rev });
  }
  throw new Error("unexpected " + url);
};
await import("./api.mjs");

const BASE = "https://x.supabase.co/functions/v1/api";
async function call(method, path, body, token = TOKEN, extra = {}) {
  const headers = { ...(token ? { authorization: "Bearer " + token } : {}), ...extra };
  let b;
  if (body !== undefined) { b = typeof body === "string" ? body : JSON.stringify(body); headers["content-type"] = "application/json; charset=utf-8"; }
  const r = await handler(new Request(BASE + path, { method, headers, body: b }));
  const txt = await r.text();
  let j = null; try { j = txt ? JSON.parse(txt) : null; } catch {}
  return { status: r.status, j, txt, h: r.headers };
}
const out = []; const t = (name, ok, info) => out.push((ok ? "ok  " : "FAIL") + " " + name + (ok || info === undefined ? "" : "  → " + JSON.stringify(info).slice(0, 300)));
const isoRe = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$/;

// ---- Abnahme (Vertrag Version 2, Abschnitt 10) ----
let r = await call("GET", "/projekte", undefined, null);
t("1a ohne Token 401 mit fehler", r.status === 401 && typeof r.j.fehler === "string", r);
r = await call("GET", "/projekte");
t("1b mit Token 200, leere Liste", r.status === 200 && r.j.anzahl === 0 && Array.isArray(r.j.projekte) && r.j.projekte.length === 0, r);
t("1c JSON mit charset utf-8", r.h.get("content-type") === "application/json; charset=utf-8");
r = await call("POST", "/projekte", { name: "Gartenhaus streichen", wo: "Farbe gekauft", naechster_schritt: "Abdeckplane auslegen" });
const id = r.j && r.j.id;
t("2 POST 201 mit neuem Projekt", r.status === 201 && /^[0-9a-z]{12}$/.test(id) && r.j.status === "aktiv" && r.j.speicherpunkt.naechster_schritt === "Abdeckplane auslegen" && r.j.speicherpunkt.wo === "Farbe gekauft" && isoRe.test(r.j.erstellt) && r.j.verlauf.length === 1, r);
t("2b in der Datenbank wie die App es ablegt", db.rows.u1 && db.rows.u1.data.v === 2 && db.rows.u1.data.projects[0].saves[0].next === "Abdeckplane auslegen" && typeof db.rows.u1.data.projects[0].mod === "number" && db.rows.u1.data.updated > 0, db.rows.u1);
r = await call("GET", "/projekte/" + id);
t("3 GET id 200", r.status === 200 && r.j.id === id && r.j.name === "Gartenhaus streichen" && r.j.verlauf.length === 1, r);
r = await call("PATCH", "/projekte/" + id, { name: "x" });
t("4 PATCH name 200", r.status === 200 && r.j.name === "x", r);
r = await call("POST", "/projekte/" + id + "/speicherpunkte", { wo: "Plane liegt", naechster_schritt: "Klebeband kleben", letzter_erledigt: true });
t("5 Speicherpunkt setzen 201, alter Schritt erledigt", r.status === 201 && r.j.speicherpunkt.naechster_schritt === "Klebeband kleben" && r.j.verlauf.length === 2 && r.j.verlauf[1].erledigt === true && isoRe.test(r.j.verlauf[1].erledigt_am) && r.j.anzahl_speicherpunkte === 2, r);
r = await call("DELETE", "/projekte/" + id);
t("6 DELETE 204 ohne Körper", r.status === 204 && r.txt === "", r);
r = await call("GET", "/projekte/" + id);
t("7 danach 404", r.status === 404 && r.j.fehler, r);
t("7b Löschung für die App vermerkt", typeof db.rows.u1.data.deleted[id] === "number" && db.rows.u1.data.projects.length === 0);

// ---- Token ----
r = await call("GET", "/projekte", undefined, OTHER); t("falscher Token 401", r.status === 401, r);
r = await call("GET", "/projekte", undefined, "abc"); t("kaputter Token 401", r.status === 401, r);
r = await call("GET", "/projekte", undefined, null, { authorization: "Basic xyz" }); t("anderes Schema 401", r.status === 401, r);
r = await call("GET", ""); t("Startpunkt nennt Version", r.status === 200 && r.j.schnittstelle === "speicherpunkt" && r.j.version === 2, r);

// ---- Liste, Suche, Filter ----
const mk = async (name, next, wo) => (await call("POST", "/projekte", { name, naechster_schritt: next, wo })).j;
const a = await mk("Steuererklärung 2026", "Lohnausweis suchen", "Ordner liegt im Büro");
await new Promise(res => setTimeout(res, 5));
const b = await mk("Brain2Win Logo", "Drei Skizzen machen");
await new Promise(res => setTimeout(res, 5));
const c = await mk("Gitarre üben", "F-Griff fünfmal greifen");
r = await call("GET", "/projekte");
t("sortiert nach geaendert, neueste zuerst", r.j.projekte.map(p => p.id).join() === [c.id, b.id, a.id].join() && r.j.anzahl === 3, r.j.projekte.map(p => p.name));
t("Liste ohne Verlauf", r.j.projekte[0].verlauf === undefined && r.j.projekte[0].speicherpunkt.naechster_schritt === "F-Griff fünfmal greifen");
r = await call("GET", "/projekte?suche=" + encodeURIComponent("ordner BÜRO"));
t("Suche: alle Wörter, Gross/Klein egal, auch im Stand", r.j.anzahl === 1 && r.j.projekte[0].id === a.id, r.j);
r = await call("GET", "/projekte?suche=skizzen"); t("Suche im Schritt", r.j.anzahl === 1 && r.j.projekte[0].id === b.id);
r = await call("GET", "/projekte?suche=nichtda"); t("Suche ohne Treffer", r.status === 200 && r.j.anzahl === 0);
r = await call("GET", "/projekte?limit=2"); t("limit", r.j.anzahl === 2);
r = await call("GET", "/projekte?limit=500"); t("limit über 100 wird 100", r.status === 200 && r.j.anzahl === 3);
r = await call("GET", "/projekte?limit=abc"); t("limit ungültig 422", r.status === 422, r);
r = await call("GET", "/projekte?limit=0"); t("limit 0 → 422", r.status === 422, r);
r = await call("GET", "/projekte?status=kaputt"); t("status ungültig 422", r.status === 422, r);

// ---- Anlegen: Prüfungen ----
r = await call("POST", "/projekte", { naechster_schritt: "x" }); t("name fehlt 400", r.status === 400 && r.j.fehler.includes("name"), r);
r = await call("POST", "/projekte", { name: "   ", naechster_schritt: "x" }); t("name leer 400", r.status === 400, r);
r = await call("POST", "/projekte", { name: "Neu" }); t("naechster_schritt fehlt 400", r.status === 400 && r.j.fehler.includes("naechster_schritt"), r);
r = await call("POST", "/projekte", { name: "x".repeat(81), naechster_schritt: "y" }); t("name zu lang 422", r.status === 422, r);
r = await call("POST", "/projekte", { name: "Neu", naechster_schritt: "y".repeat(201) }); t("Schritt zu lang 422", r.status === 422, r);
r = await call("POST", "/projekte", { name: "Neu", naechster_schritt: "y", wo: 5 }); t("wo keine Zahl 422", r.status === 422, r);
r = await call("POST", "/projekte", { name: "Neu", naechster_schritt: "y", erinnerung: "morgen" }); t("erinnerung ungültig 422", r.status === 422, r);
r = await call("POST", "/projekte", { name: "Neu", naechster_schritt: "y", erinnerung: "2026-11-20" }); t("erinnerung ohne Uhrzeit 422", r.status === 422, r);
r = await call("POST", "/projekte", { name: "gitarre ÜBEN", naechster_schritt: "y" });
t("doppelter Name (offen) 409 mit id", r.status === 409 && r.j.id === c.id, r);
r = await call("POST", "/projekte", "{kaputt"); t("kaputtes JSON 400", r.status === 400, r);
r = await call("POST", "/projekte", "[1,2]"); t("JSON-Liste statt Objekt 400", r.status === 400, r);
r = await call("POST", "/projekte", JSON.stringify({ name: "Gross", naechster_schritt: "x", wo: "z".repeat(70000) })); t("zu grosser Körper 413", r.status === 413, r);
const writesBefore = db.writes;
r = await call("POST", "/projekte", { name: "Mit Erinnerung 🌱", naechster_schritt: "Samen kaufen", erinnerung: "2026-11-20T08:00:00+01:00", id: "e_fremd", erstellt: "1999-01-01T00:00:00Z" });
const d = r.j;
t("erinnerung gespeichert (UTC), fremde id/erstellt ignoriert", r.status === 201 && d.erinnerung === "2026-11-20T07:00:00Z" && d.id !== "e_fremd" && d.erstellt !== "1999-01-01T00:00:00Z" && d.name === "Mit Erinnerung 🌱", r);
t("genau ein Schreibvorgang", db.writes === writesBefore + 1);

// ---- Ändern ----
r = await call("PATCH", "/projekte/" + d.id, {}); t("PATCH ohne Feld 400", r.status === 400, r);
r = await call("PATCH", "/projekte/" + d.id, { tags: ["x"] }); t("PATCH nur unbekanntes Feld 400", r.status === 400, r);
r = await call("PATCH", "/projekte/" + d.id, { name: "" }); t("PATCH name leer 422", r.status === 422, r);
r = await call("PATCH", "/projekte/" + d.id, { status: "pausiert" }); t("PATCH status ungültig 422", r.status === 422, r);
r = await call("PATCH", "/projekte/nichtda", { name: "x" }); t("PATCH unbekannte id 404", r.status === 404, r);
r = await call("PATCH", "/projekte/" + d.id, { naechster_schritt: "Nur den Samenladen googeln" });
t("Schritt kleiner machen", r.status === 200 && r.j.speicherpunkt.naechster_schritt === "Nur den Samenladen googeln" && r.j.anzahl_speicherpunkte === 1, r);
r = await call("PATCH", "/projekte/" + d.id, { status: "ruht" });
t("ruhen lassen löscht Erinnerung", r.status === 200 && r.j.status === "ruht" && r.j.erinnerung === null, r);
r = await call("GET", "/projekte?status=ruht"); t("Filter ruht", r.j.anzahl === 1 && r.j.projekte[0].id === d.id);
r = await call("PATCH", "/projekte/" + d.id, { status: "aktiv", erinnerung: "2020-01-01T08:00:00Z" });
t("aufwecken + fällige Erinnerung", r.status === 200 && r.j.status === "aktiv" && r.j.faellig === true, r);
r = await call("PATCH", "/projekte/" + d.id, { abschluss_notiz: "Beet ist fertig" }); t("abschluss_notiz ohne fertig 422", r.status === 422, r);
r = await call("PATCH", "/projekte/" + d.id, { status: "fertig", abschluss_notiz: "Alles gesät." });
t("abschliessen mit Notiz", r.status === 200 && r.j.status === "fertig" && isoRe.test(r.j.abgeschlossen) && r.j.speicherpunkt.abschluss === true && r.j.speicherpunkt.wo === "Alles gesät." && r.j.verlauf[1].erledigt === true && r.j.faellig === false && r.j.erinnerung === null, r);
r = await call("GET", "/projekte?status=fertig"); t("Filter fertig", r.j.anzahl === 1);
r = await call("PATCH", "/projekte/" + d.id, { status: "aktiv" }); t("fertig → aktiv nur über Speicherpunkt (409)", r.status === 409 && r.j.fehler.includes("speicherpunkte"), r);
r = await call("PATCH", "/projekte/" + d.id, { naechster_schritt: "x" }); t("Schritt ändern bei fertigem Projekt 409", r.status === 409, r);
r = await call("POST", "/projekte", { name: "Mit Erinnerung 🌱", naechster_schritt: "Zweite Runde" });
t("gleicher Name erlaubt, wenn altes fertig", r.status === 201, r);
r = await call("POST", "/projekte/" + d.id + "/speicherpunkte", { naechster_schritt: "Neue Samen holen" });
t("Speicherpunkt öffnet fertiges Projekt wieder", r.status === 201 && r.j.status === "aktiv" && r.j.abgeschlossen === null, r);
r = await call("POST", "/projekte/" + d.id + "/speicherpunkte", { naechster_schritt: "x", letzter_erledigt: "ja" }); t("letzter_erledigt kein bool 422", r.status === 422, r);
r = await call("POST", "/projekte/" + d.id + "/speicherpunkte", { wo: "nur Stand" }); t("Speicherpunkt ohne Schritt 400", r.status === 400, r);
r = await call("POST", "/projekte/nichtda/speicherpunkte", { naechster_schritt: "x" }); t("Speicherpunkt unbekanntes Projekt 404", r.status === 404, r);
r = await call("GET", "/projekte/" + d.id + "/speicherpunkte"); t("Verlauf lesen", r.status === 200 && r.j.anzahl === 3 && r.j.speicherpunkte[0].naechster_schritt === "Neue Samen holen", r);
const modBefore = db.rows.u1.data.projects.find(p => p.id === a.id).mod;
await new Promise(res => setTimeout(res, 5));
await call("PATCH", "/projekte/" + a.id, { name: "Steuern 2026" });
t("mod wird bei jeder Änderung neu gesetzt", db.rows.u1.data.projects.find(p => p.id === a.id).mod > modBefore);

// ---- Methoden und Pfade ----
r = await call("PUT", "/projekte/" + a.id, { name: "x" }); t("PUT 405 mit Allow", r.status === 405 && r.h.get("allow") === "GET, PATCH, DELETE", r);
r = await call("DELETE", "/projekte"); t("DELETE Liste 405", r.status === 405, r);
r = await call("GET", "/eintraege"); t("unbekannter Pfad 404", r.status === 404, r);
r = await call("GET", "/projekte/" + a.id + "/x"); t("unbekannter Unterpfad 404", r.status === 404, r);
let h = await handler(new Request("https://x/api/projekte", { headers: { authorization: "Bearer " + TOKEN } }));
t("Pfad ohne /functions/v1", h.status === 200);
h = await handler(new Request("https://x/functions/v1/api/v1/projekte", { headers: { authorization: "Bearer " + TOKEN } }));
t("Pfad mit /v1", h.status === 200);
h = await handler(new Request(BASE + "/projekte", { method: "OPTIONS" })); t("OPTIONS", h.status === 204);

// ---- Grenzen, Fehlerfälle ----
db.rateRetry = 17; r = await call("GET", "/projekte"); t("429 mit Retry-After", r.status === 429 && r.h.get("retry-after") === "17", r); db.rateRetry = 0;
db.down = true; r = await call("GET", "/projekte"); t("Datenbank weg → 503", r.status === 503 && r.j.fehler, r); db.down = false;
db.missing = true; r = await call("GET", "/projekte"); t("SQL nicht eingerichtet → 500 mit Hinweis", r.status === 500 && r.j.fehler.includes("supabase-setup.sql"), r); db.missing = false;

// Gleichzeitig schreibt die App: erster Schreibversuch scheitert (409), die Funktion liest neu und behält beide Änderungen.
db.conflicts = 1;
db.onConflict = () => { const row = db.rows.u1; row.data.projects.push({ id: "vonapp00001", name: "Von der App", created: Date.now(), paused: false, saves: [{ id: "s1", at: Date.now(), where: "", next: "App-Schritt" }], mod: Date.now() }); row.rev++; };
r = await call("POST", "/projekte", { name: "Während App schreibt", naechster_schritt: "Weiter" });
const names = db.rows.u1.data.projects.map(p => p.name);
t("Konflikt: neu gelesen, beide Änderungen da", r.status === 201 && names.includes("Von der App") && names.includes("Während App schreibt"), names);
db.conflicts = 99; db.onConflict = null;
r = await call("POST", "/projekte", { name: "Dauerkonflikt", naechster_schritt: "x" }); t("Dauerkonflikt → 409", r.status === 409, r);
db.conflicts = 0;
const hitsBefore = db.hits; await call("GET", "/projekte"); t("ein Aufruf zählt einmal", db.hits === hitsBefore + 1);

// Unsaubere Daten aus alten App-Versionen: nichts geht verloren, nichts stürzt ab.
db.rows.u1.data = { v: 2, projects: [null, { id: "alt1", name: "", saves: [{ where: "w" }, { at: 1, next: "ok" }], extra: "bleibt" }, { name: "ohne id" }], deleted: [], keepme: 1 };
r = await call("GET", "/projekte");
t("unsaubere Daten lesbar", r.status === 200 && r.j.anzahl === 1 && r.j.projekte[0].name === "Ohne Namen" && r.j.projekte[0].speicherpunkt.naechster_schritt === "ok", r.j);
await call("PATCH", "/projekte/alt1", { status: "ruht" });
const alt = db.rows.u1.data.projects.find(p => p.id === "alt1");
t("unbekannte Felder bleiben erhalten", alt.extra === "bleibt" && db.rows.u1.data.keepme === 1 && alt.paused === true, db.rows.u1.data);

// Erstes Schreiben ohne vorhandene Zeile (App nie angemeldet gewesen)
db.tokens[OTHER] = "u2";
r = await call("POST", "/projekte", { name: "Erstes", naechster_schritt: "Los" }, OTHER);
t("erste Zeile wird angelegt", r.status === 201 && db.rows.u2 && db.rows.u2.rev === 0, r);
r = await call("GET", "/projekte", undefined, OTHER); t("Konten bleiben getrennt", r.j.anzahl === 1 && r.j.projekte[0].name === "Erstes");

console.log(out.join("\n"));
console.log(out.some(x => x.startsWith("FAIL")) ? "SOME FAILED" : "ALL OK (" + out.length + ")");
