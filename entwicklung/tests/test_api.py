"""Schnittstelle für ZbiWeb, gegen echtes Postgres + PostgREST (siehe lokal_supabase.py).
A: Datenbank-Regeln, B: Abnahme laut SCHNITTSTELLE.md, C: App und Schnittstelle zusammen (Playwright)."""
import sys, json, pathlib, shutil, re, time, hashlib, http.server, threading, functools, urllib.request, urllib.error
sys.path.insert(0, str(pathlib.Path(__file__).parent))
import lokal_supabase as Lm

ok, why = Lm.available()
if not ok:
    print("ÜBERSPRUNGEN: " + why); sys.exit(0)
from playwright.sync_api import sync_playwright

OUT = pathlib.Path(sys.argv[2]); OUT.mkdir(parents=True, exist_ok=True)
SITE = OUT / "site"
if SITE.exists(): shutil.rmtree(SITE)
shutil.copytree(sys.argv[1], SITE)

problems = []
def check(c, m):
    if not c: problems.append(m)

L = Lm.Local().start()
def raw(method, path, body=None, headers=None):
    data = body if isinstance(body, (bytes, type(None))) else json.dumps(body).encode()
    r = urllib.request.Request(L.url + path, data=data, method=method, headers=headers or {})
    try:
        with urllib.request.urlopen(r, timeout=30) as x: b = x.read(); return x.status, (json.loads(b) if b else None), {k.lower(): v for k, v in x.headers.items()}
    except urllib.error.HTTPError as e:
        b = e.read();
        try: j = json.loads(b) if b else None
        except Exception: j = b.decode(errors="replace")
        return e.code, j, {k.lower(): v for k, v in e.headers.items()}
def rest(method, path, body=None, jwt=None, prefer=None):
    h = {"apikey": Lm.KEY, "Content-Type": "application/json"}
    if jwt: h["Authorization"] = "Bearer " + jwt
    if prefer: h["Prefer"] = prefer
    return raw(method, "/rest/v1" + path, body, h)
def api(method, path, body=None, token=None):
    """So ruft ZbiWeb die Schnittstelle auf: nur der Token, kein apikey."""
    h = {}
    if token: h["Authorization"] = "Bearer " + token
    if body is not None: h["Content-Type"] = "application/json; charset=utf-8"
    return raw(method, "/functions/v1/api" + path, body, h)

try:
    # ================= A: Datenbank =================
    m = L.signup("michael@example.ch", "geheim123"); M = m["access_token"]; MID = m["user"]["id"]
    w = L.signup("partnerin@example.ch", "geheim456"); W = w["access_token"]; WID = w["user"]["id"]

    st, j, _ = rest("POST", "/rpc/sp_api_token_new", {}); check(st in (401, 403), f"A anon darf keinen Token erzeugen ({st})")
    st, j, _ = rest("GET", "/sp_api_tokens?select=*"); check(st in (401, 403), f"A anon liest sp_api_tokens ({st})")
    st, j, _ = rest("GET", "/sp_api_tokens?select=*", jwt=M); check(st in (401, 403), f"A angemeldet liest sp_api_tokens ({st})")
    st, j, _ = rest("POST", "/rpc/sp_api_token_info", {}, jwt=M); check(st == 200 and j == {"aktiv": False}, f"A info ohne Token: {st} {j}")
    st, tok1, _ = rest("POST", "/rpc/sp_api_token_new", {}, jwt=M)
    check(st == 200 and re.fullmatch(r"sp_[0-9a-f]{64}", tok1 or ""), f"A Token erzeugen: {st} {tok1}")
    stored = L.psql("select token_hash from sp_api_tokens where user_id = '%s'" % MID)
    check(stored == hashlib.sha256(tok1.encode()).hexdigest(), "A gespeichert wird nur die Prüfsumme")
    check(tok1 not in L.psql("select row_to_json(t)::text from sp_api_tokens t"), "A Token im Klartext gespeichert")
    st, j, _ = rest("POST", "/rpc/sp_api_token_info", {}, jwt=M)
    check(st == 200 and j["aktiv"] is True and isinstance(j["erstellt"], int) and j["zuletzt"] is None, f"A info: {j}")

    # Revisionszähler und bedingtes Schreiben
    st, _, _ = rest("POST", "/sp_state", {"user_id": MID, "data": {"v": 2, "projects": [], "deleted": {}}, "updated_at": 1}, jwt=M, prefer="return=minimal")
    check(st == 201, f"A Zeile anlegen {st}")
    st, j, _ = rest("POST", "/sp_state", {"user_id": MID, "data": {"v": 2, "projects": []}, "updated_at": 1}, jwt=M, prefer="return=minimal")
    check(st == 409 and j.get("code") == "23505", f"A doppeltes Anlegen gibt 409/23505: {st} {j}")
    st, j, _ = rest("GET", "/sp_state?select=data,updated_at,rev", jwt=M); check(j[0]["rev"] == 0, f"A rev beginnt bei 0: {j}")
    st, j, _ = rest("PATCH", f"/sp_state?user_id=eq.{MID}&rev=eq.0&select=rev", {"data": {"v": 2, "projects": []}, "updated_at": 2}, jwt=M, prefer="return=representation")
    check(st == 200 and j == [{"rev": 1}], f"A bedingtes Schreiben klappt: {st} {j}")
    st, j, _ = rest("PATCH", f"/sp_state?user_id=eq.{MID}&rev=eq.0&select=rev", {"data": {"v": 2, "projects": []}, "updated_at": 3}, jwt=M, prefer="return=representation")
    check(st == 200 and j == [], f"A veraltete rev schreibt nicht: {st} {j}")
    st, j, _ = rest("POST", "/sp_state?on_conflict=user_id", {"user_id": MID, "data": {"v": 2, "projects": []}, "updated_at": 4}, jwt=M, prefer="resolution=merge-duplicates,return=minimal")
    check(st in (200, 201), f"A alte App-Version (upsert) geht weiterhin: {st} {j}")
    check(L.psql(f"select rev from sp_state where user_id = '{MID}'") == "2", "A upsert erhöht rev")
    st, j, _ = rest("PATCH", f"/sp_state?user_id=eq.{MID}&rev=eq.2&select=rev", {"data": {"v": 2, "projects": [{"id": "x"}]}}, jwt=W, prefer="return=representation")
    check(st == 200 and j == [], f"A fremde Zeile nicht änderbar: {st} {j}")
    st, j, _ = rest("PATCH", f"/sp_state?user_id=eq.{MID}&select=rev", {"rev": 99}, jwt=M, prefer="return=representation")
    check(j == [{"rev": 3}], f"A rev lässt sich nicht von Hand setzen: {j}")

    # Token direkt an der Datenbank
    st, j, _ = rest("POST", "/rpc/sp_api_open", {"p_token": tok1}); check(st == 200 and j["status"] == 200 and j["rev"] == 3, f"A open: {j}")
    st, j, _ = rest("POST", "/rpc/sp_api_open", {"p_token": "sp_" + "0" * 64}); check(j["status"] == 401, f"A open falscher Token: {j}")
    st, j, _ = rest("POST", "/rpc/sp_api_open", {"p_token": "' or 1=1 --"}); check(j["status"] == 401, f"A open Unsinn: {j}")
    st, j, _ = rest("POST", "/rpc/sp_api_write", {"p_token": tok1, "p_rev": 3, "p_data": {"projects": "kaputt"}}); check(j["status"] == 422, f"A write prüft Form: {j}")
    st, j, _ = rest("POST", "/rpc/sp_api_write", {"p_token": tok1, "p_rev": 1, "p_data": {"v": 2, "projects": []}}); check(j["status"] == 409, f"A write mit alter rev 409: {j}")
    check(L.psql(f"select last_used_at is not null from sp_api_tokens where user_id = '{MID}'") == "t", "A zuletzt benutzt wird vermerkt")
    # Ratenbegrenzung: 60 pro Minute
    L.psql(f"update sp_api_tokens set window_start = now(), window_hits = 0 where user_id = '{MID}'")
    codes = [rest("POST", "/rpc/sp_api_open", {"p_token": tok1})[1]["status"] for _ in range(61)]
    check(codes[:60] == [200] * 60 and codes[60] == 429, f"A 60 erlaubt, 61. gesperrt: {codes[55:]}")
    j = rest("POST", "/rpc/sp_api_open", {"p_token": tok1})[1]; check(j["status"] == 429 and 1 <= j["retry"] <= 60, f"A retry-Angabe: {j}")
    j = rest("POST", "/rpc/sp_api_open", {"p_token": tok1, "p_count": False})[1]; check(j["status"] == 200, "A Neulesen bei Konflikt zählt nicht")
    L.psql(f"update sp_api_tokens set window_start = now() - interval '61 seconds' where user_id = '{MID}'")
    j = rest("POST", "/rpc/sp_api_open", {"p_token": tok1})[1]; check(j["status"] == 200, "A nach einer Minute wieder offen")

    # ================= B: Abnahme wie ZbiWeb =================
    rest("PATCH", f"/sp_state?user_id=eq.{MID}", {"data": {"v": 2, "projects": [], "deleted": {}}}, jwt=M)
    st, j, h = api("GET", "/projekte"); check(st == 401 and "fehler" in j, f"B1 ohne Token: {st} {j}")
    st, j, h = api("GET", "/projekte", token=tok1)
    check(st == 200 and j == {"projekte": [], "anzahl": 0} and h.get("content-type") == "application/json; charset=utf-8", f"B1 mit Token: {st} {j} {h.get('content-type')}")
    st, j, _ = api("POST", "/projekte", {"name": "Steuererklärung 2026", "wo": "Ordner liegt im Büro", "naechster_schritt": "Lohnausweis suchen"}, tok1)
    pid = (j or {}).get("id"); check(st == 201 and pid and j["speicherpunkt"]["naechster_schritt"] == "Lohnausweis suchen", f"B2 anlegen: {st} {j}")
    st, j, _ = api("GET", f"/projekte/{pid}", token=tok1); check(st == 200 and j["name"] == "Steuererklärung 2026", f"B3 lesen: {st} {j}")
    st, j, _ = api("PATCH", f"/projekte/{pid}", {"name": "x"}, tok1); check(st == 200 and j["name"] == "x", f"B4 ändern: {st} {j}")
    st, j, _ = api("POST", f"/projekte/{pid}/speicherpunkte", {"wo": "Lohnausweis gefunden", "naechster_schritt": "Formular öffnen", "letzter_erledigt": True}, tok1)
    check(st == 201 and j["anzahl_speicherpunkte"] == 2 and j["verlauf"][1]["erledigt"], f"B5 Speicherpunkt: {st} {j}")
    st, j, _ = api("DELETE", f"/projekte/{pid}", token=tok1); check(st == 204 and j is None, f"B6 löschen: {st} {j}")
    st, j, _ = api("GET", f"/projekte/{pid}", token=tok1); check(st == 404, f"B7 danach 404: {st}")
    # Abnahme genau wie in SCHNITTSTELLE.md, Abschnitt 12
    ab = [api("GET", "/projekte")[0], api("GET", "/projekte", token=tok1)[0]]
    st, j, _ = api("POST", "/projekte", {"name": "Abnahme ZbiWeb", "naechster_schritt": "Test durchführen"}, tok1); ab.append(st); aid = (j or {}).get("id")
    ab.append(api("GET", f"/projekte/{aid}", token=tok1)[0])
    st, j, _ = api("PATCH", f"/projekte/{aid}", {"name": "Abnahme ZbiWeb x"}, tok1); ab.append(st if j.get("name") == "Abnahme ZbiWeb x" else -st)
    st, j, _ = api("POST", f"/projekte/{aid}/speicherpunkte", {"naechster_schritt": "Aufräumen", "letzter_erledigt": True}, tok1); ab.append(st if j.get("anzahl_speicherpunkte") == 2 else -st)
    ab.append(api("DELETE", f"/projekte/{aid}", token=tok1)[0]); ab.append(api("GET", f"/projekte/{aid}", token=tok1)[0])
    check(ab == [401, 200, 201, 200, 200, 201, 204, 404], f"B Abnahme laut Vertrag: {ab}")
    st, j, _ = api("GET", "/eintraege", token=tok1); check(st == 404, f"B alter Pfad /eintraege gibt 404: {st}")
    st, j, h = api("PUT", "/projekte", {"a": 1}, tok1); check(st == 405 and h.get("allow") == "GET, POST", f"B 405: {st} {h.get('allow')}")
    L.psql(f"update sp_api_tokens set window_start = now(), window_hits = 60 where user_id = '{MID}'")
    st, j, h = api("GET", "/projekte", token=tok1); check(st == 429 and 1 <= int(h.get("retry-after", "0")) <= 60, f"B 429 mit Retry-After: {st} {h}")
    L.psql(f"update sp_api_tokens set window_hits = 0 where user_id = '{MID}'")
    st, tw, _ = rest("POST", "/rpc/sp_api_token_new", {}, jwt=W)
    st, j, _ = api("POST", "/projekte", {"name": "Nur ihres", "naechster_schritt": "Kunde anrufen"}, tw); check(st == 201, f"B Partnerin legt an: {st}")
    st, j, _ = api("GET", "/projekte", token=tok1); check(all(p["name"] != "Nur ihres" for p in j["projekte"]), "B Konten getrennt (Michael sieht ihres)")
    st, j, _ = api("GET", "/projekte", token=tw); check(j["anzahl"] == 1 and j["projekte"][0]["name"] == "Nur ihres", f"B Konten getrennt: {j}")

    # ================= C: App und Schnittstelle zusammen =================
    class Q(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *a): pass
    web = http.server.ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(Q, directory=str(SITE.resolve())))
    threading.Thread(target=web.serve_forever, daemon=True).start()
    URL = f"http://127.0.0.1:{web.server_address[1]}/index.html"
    idx = SITE / "index.html"
    idx.write_text(idx.read_text(encoding="utf-8").replace("connect-src 'self' https://satqwruqmwgcflcggbul.supabase.co", "connect-src 'self' " + L.url), encoding="utf-8")
    INIT = "window.SP_CONFIG = { url: %s, key: %s };" % (json.dumps(L.url), json.dumps(Lm.KEY))

    def state_names():
        d = json.loads(L.psql(f"select data::text from sp_state where user_id = '{MID}'") or "{}")
        return [p.get("name") for p in d.get("projects", [])]

    with sync_playwright() as p:
        b = p.chromium.launch()
        errs = []
        def device(name, mobile=True, dark=False):
            ctx = b.new_context(viewport={"width": 390, "height": 844} if mobile else {"width": 1200, "height": 900}, locale="de-CH",
                                timezone_id="Europe/Zurich", color_scheme="dark" if dark else "light")
            ctx.add_init_script(INIT)
            ctx.route(re.compile(r".*fonts\.(googleapis|gstatic)\.com.*"), lambda r: r.abort())
            pg = ctx.new_page()
            pg.on("pageerror", lambda e: errs.append(name + ": " + str(e)))
            pg.on("console", lambda msg: errs.append(name + " console: " + msg.text) if msg.type == "error" and "Failed to load resource" not in msg.text else None)
            pg.goto(URL); pg.wait_for_timeout(300)
            return ctx, pg
        def login(pg, email, pw):
            pg.click("button:has-text('Einstellungen')"); pg.fill("#f-email", email); pg.fill("#f-pass", pw)
            pg.click("#account button[type=submit]"); pg.wait_for_timeout(900)
        def resync(pg, ms=1500):
            pg.evaluate("document.dispatchEvent(new Event('visibilitychange'))"); pg.wait_for_timeout(ms)
        def home(pg):
            if pg.locator("button.pill:has-text('Übersicht')").count(): pg.click("button.pill:has-text('Übersicht')")
            pg.wait_for_timeout(150)

        ctx, ph = device("phone")
        login(ph, "michael@example.ch", "geheim123")
        check(ph.evaluate("!!localStorage.getItem('speicherpunkt.session')"), "C Anmeldung in der App")
        # Token in der App erzeugen (ersetzt den Token aus Teil A)
        ph.click("button:has-text('Einstellungen')") if ph.locator("#api").count() == 0 else None
        check(ph.locator("#api").count() == 1 and "Einrichten" in ph.text_content("#api"), "C Kasten Schnittstelle fehlt")
        ph.screenshot(path=str(OUT / "c1_einstellungen_zu.png"), full_page=True)
        ph.click("[data-action=api-open]"); ph.wait_for_timeout(500)
        check("Ein Token ist aktiv" in ph.text_content("#api-status"), "C Status zeigt aktiven Token: " + ph.text_content("#api-status"))
        check(L.url + "/functions/v1/api" == ph.text_content("#api-url"), "C Adresse der Schnittstelle: " + ph.text_content("#api-url"))
        ph.click("[data-action=api-new]"); check("hört sofort auf" in ph.text_content("#api"), "C Rückfrage vor neuem Token")
        ph.click("[data-action=api-new-yes]"); ph.wait_for_timeout(500)
        tok = ph.input_value("#f-token")
        check(re.fullmatch(r"sp_[0-9a-f]{64}", tok), "C neuer Token sichtbar: " + tok)
        check(ph.evaluate("document.activeElement.id") == "f-token", "C Token ist markiert")
        ph.screenshot(path=str(OUT / "c2_token_neu.png"), full_page=True)
        check(api("GET", "/projekte", token=tok1)[0] == 401, "C alter Token gilt nicht mehr")
        check(api("GET", "/projekte", token=tok)[0] == 200, "C neuer Token gilt")
        check(tok not in ph.evaluate("JSON.stringify(localStorage)"), "C Token landet nicht im Gerätespeicher")
        ph.click("[data-action=api-done]"); check(ph.locator("#f-token").count() == 0, "C Token verschwindet nach Fertig")

        # ZbiWeb legt ein Projekt an -> erscheint in der App
        st, j, _ = api("POST", "/projekte", {"name": "Von ZbiWeb", "wo": "Idee notiert", "naechster_schritt": "Ordner öffnen"}, tok)
        zid = j["id"]
        home(ph); resync(ph)
        check("Von ZbiWeb" in ph.text_content("main") and "Ordner öffnen" in ph.text_content("main"), "C Projekt von der Schnittstelle erscheint in der App")
        ph.screenshot(path=str(OUT / "c3_app_zeigt_api_projekt.png"), full_page=True)

        # In der App einen Speicherpunkt setzen -> ZbiWeb liest ihn
        ph.click(f".proj:has-text('Von ZbiWeb')") if ph.locator(".proj:has-text('Von ZbiWeb')").count() else ph.get_by_role("button", name="Weitermachen", exact=True).click()
        ph.wait_for_timeout(200)
        ph.click("[data-action=save]"); ph.fill("#f-where", "Ordner ist offen"); ph.fill("#f-next", "Erste Seite lesen")
        ph.click("form[data-form=save] button[type=submit]"); ph.wait_for_timeout(2200)
        st, j, _ = api("GET", f"/projekte/{zid}", token=tok)
        check(j["speicherpunkt"]["naechster_schritt"] == "Erste Seite lesen" and j["speicherpunkt"]["wo"] == "Ordner ist offen" and j["anzahl_speicherpunkte"] == 2, f"C Schnittstelle sieht Speicherpunkt aus der App: {j}")

        # Gleichzeitig: Die Schnittstelle schreibt genau zwischen Lesen und Schreiben der App.
        fired = []
        def zwischendurch():
            fired.append(api("POST", "/projekte", {"name": "Gleichzeitig von ZbiWeb", "naechster_schritt": "Nicht verlieren"}, tok)[0])
        L.after_state_get = zwischendurch; calls_before = len(L.calls)
        ph.click("text=+ Neues Projekt"); ph.fill("#f-name", "In der App"); ph.fill("#f-next", "Lokal angelegt")
        ph.click("form[data-form=save] button[type=submit]"); ph.wait_for_timeout(3000)
        names = state_names()
        check(fired == [201], f"C Haken ausgelöst: {fired}")
        check("Gleichzeitig von ZbiWeb" in names and "In der App" in names, f"C nichts geht verloren bei gleichzeitigem Schreiben: {names}")
        patches = L.calls[calls_before:].count(("PATCH", "/rest/v1/sp_state"))
        check(patches == 2, f"C App schreibt nach dem Konflikt genau einmal nochmals: {patches} PATCH")
        resync(ph)
        check("Gleichzeitig von ZbiWeb" in ph.text_content("main") and "In der App" in ph.text_content("main"), "C App zeigt beide Projekte")
        n0 = len(L.calls); resync(ph); resync(ph)
        idle = [c for c in L.calls[n0:] if c[1] == "/rest/v1/sp_state" and c[0] != "GET"]
        check(not idle and L.calls[n0:].count(("GET", "/rest/v1/sp_state")) == 2, f"C Abgleich ohne Änderung liest nur und schreibt nichts: {L.calls[n0:]}")

        # ZbiWeb lässt ruhen und löscht -> App folgt
        api("PATCH", f"/projekte/{zid}", {"status": "ruht"}, tok)
        gid = next(x["id"] for x in api("GET", "/projekte?suche=gleichzeitig", token=tok)[1]["projekte"])
        api("DELETE", f"/projekte/{gid}", token=tok)
        resync(ph)
        check("Gleichzeitig von ZbiWeb" not in ph.text_content("main"), "C Löschung über die Schnittstelle kommt in der App an")
        check(ph.locator(".proj.resting:has-text('Von ZbiWeb')").count() == 1 or "ruht" in ph.text_content("main").lower(), "C Ruhen über die Schnittstelle kommt in der App an")
        ph.screenshot(path=str(OUT / "c4_app_nach_api.png"), full_page=True)

        # Zweites Gerät (PC, dunkel) sieht dasselbe
        ctx2, pc = device("pc", mobile=False, dark=True)
        login(pc, "michael@example.ch", "geheim123")
        check("In der App" in pc.text_content("main") and "Gleichzeitig von ZbiWeb" not in pc.text_content("main"), "C PC hat denselben Stand")
        pc.click("button:has-text('Einstellungen')"); pc.click("[data-action=api-open]"); pc.wait_for_timeout(500)
        check("zuletzt benutzt" in pc.text_content("#api-status"), "C PC zeigt, wann der Token zuletzt benutzt wurde: " + pc.text_content("#api-status"))
        pc.screenshot(path=str(OUT / "c5_pc_dunkel_einstellungen.png"), full_page=True)
        # Token löschen
        pc.click("[data-action=api-revoke]"); pc.click("[data-action=api-revoke-yes]"); pc.wait_for_timeout(500)
        check("Kein Token aktiv" in pc.text_content("#api-status"), "C nach Löschen kein Token aktiv")
        check(api("GET", "/projekte", token=tok)[0] == 401, "C gelöschter Token gilt nicht mehr")
        pc.click("[data-action=api-new-yes]"); pc.wait_for_timeout(500); tok2 = pc.input_value("#f-token")
        check(api("GET", "/projekte", token=tok2)[0] == 200, "C neuer Token nach dem Löschen")

        # Ältere Datenbank ohne rev-Spalte: App gleicht weiterhin ab (wie bisher, ohne Konfliktschutz)
        L.psql("drop trigger if exists sp_state_bump on public.sp_state; alter table public.sp_state drop column rev")
        L.reload_schema()
        home(ph); ph.click("text=+ Neues Projekt"); ph.fill("#f-name", "Ohne rev"); ph.fill("#f-next", "Trotzdem speichern")
        ph.click("form[data-form=save] button[type=submit]"); ph.wait_for_timeout(2500)
        check("Ohne rev" in state_names(), "C ohne rev-Spalte wird trotzdem abgeglichen")
        check(ph.evaluate("JSON.parse(localStorage.getItem('speicherpunkt.pending') || 'null')") is None, "C ohne rev: nichts bleibt hängen")
        L.psql_file(Lm.APP / "supabase-setup.sql"); L.reload_schema()
        check(L.psql(f"select rev from sp_state where user_id = '{MID}'") == "0", "C Setup erneut ausgeführt: rev wieder da")
        st, j, _ = api("POST", "/projekte", {"name": "Nach Reparatur", "naechster_schritt": "x"}, tok2); check(st == 201, f"C Schnittstelle nach erneutem Setup: {st} {j}")

        # Konto löschen nimmt den Token mit
        pc.click("button:has-text('Übersicht')"); pc.click("button:has-text('Einstellungen')")
        pc.click("[data-action=delete-account]"); pc.fill("#f-delete", "löschen"); pc.click("[data-action=delete-account-yes]"); pc.wait_for_timeout(800)
        check(L.psql(f"select count(*) from sp_api_tokens where user_id = '{MID}'") == "0", "C Konto löschen entfernt den Token")
        check(api("GET", "/projekte", token=tok2)[0] == 401, "C nach Kontolöschung 401")
        check(api("GET", "/projekte", token=tw)[1]["anzahl"] == 1, "C Konto der Partnerin unberührt")
        b.close()
    check(not errs, "Fehler in der Seite: " + "; ".join(errs[:5]))
finally:
    fnlog = (L.tmp / "fn.log").read_text(errors="replace") if (L.tmp / "fn.log").exists() else ""
    L.stop()

if fnlog.strip() not in ("", "bereit"): print("Ausgabe der Funktion:\n" + fnlog[-1500:])
print("\n".join("PROBLEM: " + x for x in problems) if problems else "ALL OK")
