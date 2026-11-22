"""App und Datenbank zusammen, gegen echtes Postgres + PostgREST (siehe lokal_supabase.py).
A: Datenbank-Regeln und Revisionszähler, B: Aufräumen der Schnittstelle aus Version 8,
C: Abgleich in der App (Playwright): zwei Geräte, gleichzeitiges Schreiben, ältere Datenbank ohne rev, Konto löschen."""
import sys, json, pathlib, shutil, re, http.server, threading, functools, urllib.request, urllib.error
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
def rest(method, path, body=None, jwt=None, prefer=None):
    h = {"apikey": Lm.KEY, "Content-Type": "application/json"}
    if jwt: h["Authorization"] = "Bearer " + jwt
    if prefer: h["Prefer"] = prefer
    r = urllib.request.Request(L.url + "/rest/v1" + path, data=None if body is None else json.dumps(body).encode(), method=method, headers=h)
    try:
        with urllib.request.urlopen(r, timeout=30) as x: b = x.read(); return x.status, (json.loads(b) if b else None)
    except urllib.error.HTTPError as e:
        b = e.read()
        try: return e.code, json.loads(b) if b else None
        except Exception: return e.code, b.decode(errors="replace")

try:
    # ================= A: Datenbank =================
    m = L.signup("michael@example.ch", "geheim123"); M = m["access_token"]; MID = m["user"]["id"]
    w = L.signup("partnerin@example.ch", "geheim456"); W = w["access_token"]; WID = w["user"]["id"]
    st, _ = rest("POST", "/sp_state", {"user_id": MID, "data": {"v": 2, "projects": [], "deleted": {}}, "updated_at": 1}, jwt=M, prefer="return=minimal")
    check(st == 201, f"A Zeile anlegen {st}")
    st, j = rest("POST", "/sp_state", {"user_id": MID, "data": {"v": 2, "projects": []}, "updated_at": 1}, jwt=M, prefer="return=minimal")
    check(st == 409 and j.get("code") == "23505", f"A doppeltes Anlegen gibt 409/23505: {st} {j}")
    st, j = rest("GET", "/sp_state?select=data,updated_at,rev", jwt=M); check(j[0]["rev"] == 0, f"A rev beginnt bei 0: {j}")
    st, j = rest("PATCH", f"/sp_state?user_id=eq.{MID}&rev=eq.0&select=rev", {"data": {"v": 2, "projects": []}, "updated_at": 2}, jwt=M, prefer="return=representation")
    check(st == 200 and j == [{"rev": 1}], f"A bedingtes Schreiben klappt: {st} {j}")
    st, j = rest("PATCH", f"/sp_state?user_id=eq.{MID}&rev=eq.0&select=rev", {"data": {"v": 2, "projects": []}, "updated_at": 3}, jwt=M, prefer="return=representation")
    check(st == 200 and j == [], f"A veraltete rev schreibt nicht: {st} {j}")
    st, j = rest("POST", "/sp_state?on_conflict=user_id", {"user_id": MID, "data": {"v": 2, "projects": []}, "updated_at": 4}, jwt=M, prefer="resolution=merge-duplicates,return=minimal")
    check(st in (200, 201), f"A alte App-Version (upsert) geht weiterhin: {st} {j}")
    check(L.psql(f"select rev from sp_state where user_id = '{MID}'") == "2", "A upsert erhöht rev")
    st, j = rest("PATCH", f"/sp_state?user_id=eq.{MID}&rev=eq.2&select=rev", {"data": {"v": 2, "projects": [{"id": "x"}]}}, jwt=W, prefer="return=representation")
    check(st == 200 and j == [], f"A fremde Zeile nicht änderbar: {st} {j}")
    st, j = rest("GET", "/sp_state?select=data", jwt=W); check(j == [], f"A fremde Zeile nicht lesbar: {j}")
    st, j = rest("GET", "/sp_state?select=data"); check(st in (401, 403) or j == [], f"A ohne Anmeldung nichts lesbar: {st} {j}")
    st, j = rest("PATCH", f"/sp_state?user_id=eq.{MID}&select=rev", {"rev": 99}, jwt=M, prefer="return=representation")
    check(j == [{"rev": 3}], f"A rev lässt sich nicht von Hand setzen: {j}")

    # ================= B: Aufräumen der Schnittstelle aus Version 8 =================
    L.psql("""create table if not exists public.sp_api_tokens (user_id uuid primary key references auth.users (id) on delete cascade, token_hash text);
      create or replace function public.sp_api_open(p_token text, p_count boolean default true) returns jsonb language sql as $$ select '{}'::jsonb $$;
      create or replace function public.sp_api_write(p_token text, p_rev bigint, p_data jsonb) returns jsonb language sql as $$ select '{}'::jsonb $$;
      create or replace function public.sp_api_token_new() returns text language sql as $$ select 'x' $$;
      create or replace function public.sp_api_token_info() returns json language sql as $$ select '{}'::json $$;
      create or replace function public.sp_api_token_revoke() returns void language sql as $$ select $$;""")
    L.psql(f"insert into sp_api_tokens values ('{MID}', 'abc')")
    data_before = L.psql(f"select data::text || rev from sp_state where user_id = '{MID}'")
    L.psql_file(Lm.APP / "supabase-setup.sql"); L.reload_schema()
    left = L.psql("select count(*) from pg_proc where proname like 'sp_api%'") + "/" + L.psql("select count(*) from pg_class where relname = 'sp_api_tokens'")
    check(left == "0/0", f"B Teile der Schnittstelle nicht aufgeräumt: {left}")
    check(L.psql(f"select data::text || rev from sp_state where user_id = '{MID}'") == data_before, "B Aufräumen hat Projekte oder rev verändert")
    st, j = rest("POST", "/rpc/sp_api_open", {"p_token": "sp_" + "0" * 64}); check(st == 404, f"B sp_api_open nicht mehr erreichbar: {st}")
    L.psql_file(Lm.APP / "supabase-setup.sql"); check(True, "zweimal ausführen geht")

    # ================= C: Abgleich in der App =================
    class Q(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *a): pass
    web = http.server.ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(Q, directory=str(SITE.resolve())))
    threading.Thread(target=web.serve_forever, daemon=True).start()
    URL = f"http://127.0.0.1:{web.server_address[1]}/index.html"
    idx = SITE / "index.html"
    idx.write_text(idx.read_text(encoding="utf-8").replace("connect-src 'self' https://satqwruqmwgcflcggbul.supabase.co", "connect-src 'self' " + L.url), encoding="utf-8")
    INIT = "window.SP_CONFIG = { url: %s, key: %s };" % (json.dumps(L.url), json.dumps(Lm.KEY))

    def db_state():
        return json.loads(L.psql(f"select data::text from sp_state where user_id = '{MID}'") or "{}")
    def names(): return [p.get("name") for p in db_state().get("projects", [])]

    with sync_playwright() as p:
        b = p.chromium.launch()
        errs = []
        def device(name, mobile=True, dark=False):
            ctx = b.new_context(viewport={"width": 390, "height": 844} if mobile else {"width": 1200, "height": 900}, locale="de-CH",
                                timezone_id="Europe/Zurich", color_scheme="dark" if dark else "light")
            ctx.add_init_script(INIT)
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
        def new_project(pg, name, step, wait=2200):
            pg.click("text=+ Neues Projekt"); pg.fill("#f-name", name); pg.fill("#f-next", step)
            pg.click("form[data-form=save] button[type=submit]"); pg.wait_for_timeout(wait)

        ctx, ph = device("phone")
        login(ph, "michael@example.ch", "geheim123")
        check(ph.evaluate("!!localStorage.getItem('speicherpunkt.session')"), "C Anmeldung in der App")
        new_project(ph, "Steuererklärung", "Lohnausweis suchen")
        check("Steuererklärung" in names(), f"C Projekt vom Handy in der Datenbank: {names()}")

        ctx2, pc = device("pc", mobile=False, dark=True)
        login(pc, "michael@example.ch", "geheim123")
        check("Lohnausweis suchen" in pc.text_content("main"), "C PC sieht Projekt vom Handy")

        # Gleichzeitig: Der PC schreibt genau zwischen Lesen und Schreiben des Handys.
        fired = []
        def pc_schreibt_dazwischen():
            st, rows = rest("GET", "/sp_state?select=data,rev", jwt=L.session(MID, "michael@example.ch")["access_token"])
            d = rows[0]["data"]; t = 1795000000000 + len(d["projects"])
            d["projects"].append({"id": "vompc0000001", "name": "Vom PC dazwischen", "created": t, "paused": False, "finished": None, "remindAt": None, "mod": 9e12,
                                  "saves": [{"id": "s1", "at": t, "where": "", "next": "Nicht verlieren"}]})
            st, j = rest("PATCH", f"/sp_state?user_id=eq.{MID}&rev=eq.{rows[0]['rev']}&select=rev", {"data": d}, jwt=L.session(MID, "michael@example.ch")["access_token"], prefer="return=representation")
            fired.append(len(j or []))
        L.after_state_get = pc_schreibt_dazwischen; n0 = len(L.calls)
        new_project(ph, "Auf dem Handy", "Lokal angelegt", wait=3000)
        check(fired == [1], f"C Testhaken ausgelöst: {fired}")
        check("Vom PC dazwischen" in names() and "Auf dem Handy" in names(), f"C nichts geht verloren bei gleichzeitigem Schreiben: {names()}")
        patches = L.calls[n0:].count(("PATCH", "/rest/v1/sp_state"))
        check(patches == 3, f"C einmal der PC, dann das Handy zweimal (abgewiesen, dann nach neuem Lesen): {patches} PATCH")
        resync(ph); resync(pc)
        for dev, pg in (("Handy", ph), ("PC", pc)):
            check("Vom PC dazwischen" in pg.text_content("main") and "Auf dem Handy" in pg.text_content("main"), f"C {dev} zeigt beide Projekte")

        # Abgleich ohne Änderung liest nur
        n0 = len(L.calls); resync(ph); resync(ph); resync(pc)
        idle = [c for c in L.calls[n0:] if c[1] == "/rest/v1/sp_state" and c[0] != "GET"]
        check(not idle and L.calls[n0:].count(("GET", "/rest/v1/sp_state")) == 3, f"C Abgleich ohne Änderung schreibt nichts: {L.calls[n0:]}")

        # Beide Geräte ändern verschiedene Projekte, dann Abgleich
        ph.click(".proj:has-text('Steuererklärung')") if ph.locator(".proj:has-text('Steuererklärung')").count() else ph.get_by_role("button", name="Weitermachen", exact=True).click()
        ph.wait_for_timeout(200); ph.click("[data-action=save]"); ph.fill("#f-where", "Lohnausweis gefunden"); ph.fill("#f-next", "Formular öffnen")
        ph.click("form[data-form=save] button[type=submit]")
        new_project(pc, "Vom PC", "Am PC angelegt", wait=2500)
        resync(ph); resync(pc)
        stx = db_state(); steuer = next(p for p in stx["projects"] if p["name"] == "Steuererklärung")
        check(steuer["saves"][-1]["next"] == "Formular öffnen" and "Vom PC" in names(), f"C beide Änderungen in der Datenbank: {names()}")
        check("Formular öffnen" in pc.text_content("main") or "Steuererklärung" in pc.text_content("main"), "C PC sieht Änderung vom Handy")

        # Einstellungen: keine Spur der Schnittstelle
        pc.click("button:has-text('Einstellungen')")
        check(pc.locator("#api").count() == 0 and "Token" not in pc.text_content("main"), "C Schnittstelle noch sichtbar")
        pc.screenshot(path=str(OUT / "c_pc_dunkel_einstellungen.png"), full_page=True)
        pc.click("button:has-text('Übersicht')")

        # Ältere Datenbank ohne rev-Spalte: App gleicht weiterhin ab
        L.psql("drop trigger if exists sp_state_bump on public.sp_state; alter table public.sp_state drop column rev")
        L.reload_schema()
        new_project(ph, "Ohne rev", "Trotzdem speichern", wait=2500)
        check("Ohne rev" in names(), "C ohne rev-Spalte wird trotzdem abgeglichen")
        check(ph.evaluate("localStorage.getItem('speicherpunkt.pending')") is None, "C ohne rev: nichts bleibt hängen")
        L.psql_file(Lm.APP / "supabase-setup.sql"); L.reload_schema()
        check(L.psql(f"select rev from sp_state where user_id = '{MID}'") == "0", "C Setup erneut ausgeführt: rev wieder da")
        new_project(pc, "Nach Reparatur", "x", wait=2500)
        check("Nach Reparatur" in names() and "Ohne rev" in names(), f"C nach erneutem Setup: {names()}")

        # Konto löschen
        pc.click("button:has-text('Einstellungen')")
        pc.click("[data-action=delete-account]"); pc.fill("#f-delete", "löschen"); pc.click("[data-action=delete-account-yes]"); pc.wait_for_timeout(800)
        check(L.psql(f"select count(*) from sp_state where user_id = '{MID}'") == "0", "C Konto löschen entfernt die Projekte")
        check(L.psql(f"select count(*) from auth.users where id = '{MID}'") == "0", "C Konto löschen entfernt das Konto")
        check(L.psql(f"select count(*) from auth.users where id = '{WID}'") == "1", "C Konto der Partnerin unberührt")
        b.close()
    check(not errs, "Fehler in der Seite: " + "; ".join(errs[:5]))
finally:
    L.stop()

print("\n".join("PROBLEM: " + x for x in problems) if problems else "ALL OK")
