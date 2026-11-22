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

    # ================= D: Erinnerungen (Push) und anonyme Zählung =================
    import time as _t
    x = L.signup("push@example.ch", "geheim789"); X = x["access_token"]; XID = x["user"]["id"]
    for tbl in ("sp_push_subs", "sp_push_sent", "sp_push_keys", "sp_push_nonce", "sp_visits", "sp_wiederkehr"):
        for who, tok in (("anon", None), ("angemeldet", X)):
            st, j = rest("GET", f"/{tbl}?select=*", jwt=tok); check(st in (401, 403), f"D {who} darf {tbl} nicht lesen ({st})")
    for fn in ("sp_push_tick", "sp_push_nonce_ok", "sp_push_zeitplan"):
        st, j = rest("POST", f"/rpc/{fn}", {"p_nonce": "11111111-2222-4333-8444-555555555555"} if fn.endswith("_ok") else {}, jwt=X); check(st in (401, 403, 404), f"D {fn} von aussen aufrufbar ({st})")
    st, j = rest("POST", "/rpc/sp_push_public_key", {}); check(st in (401, 403), f"D anon bekommt keinen Schlüssel ({st})")
    st, j = rest("POST", "/rpc/sp_push_public_key", {}, jwt=X); check(st == 200 and j is None, f"D vor dem ersten Lauf kein Schlüssel: {st} {j}")
    EP = "https://fcm.googleapis.com/fcm/send/geraet-1"; KEYS = {"p_p256dh": "B" + "A" * 86, "p_auth": "A" * 22}
    st, j = rest("POST", "/rpc/sp_push_subscribe", {"p_endpoint": EP, **KEYS}); check(st in (401, 403), f"D anon kann kein Gerät anmelden ({st})")
    st, j = rest("POST", "/rpc/sp_push_subscribe", {"p_endpoint": "http://unsicher.example/x", **KEYS}, jwt=X); check(st == 400, f"D Adresse ohne https abgelehnt ({st})")
    st, j = rest("POST", "/rpc/sp_push_subscribe", {"p_endpoint": EP, "p_p256dh": "kurz", "p_auth": "A" * 22}, jwt=X); check(st == 400, f"D kaputter Schlüssel abgelehnt ({st})")
    st, j = rest("POST", "/rpc/sp_push_subscribe", {"p_endpoint": EP, **KEYS}, jwt=X); check(st in (200, 204), f"D Gerät anmelden ({st} {j})")
    st, j = rest("POST", "/rpc/sp_push_subscribe", {"p_endpoint": EP, **KEYS}, jwt=X); check(L.psql("select count(*) from sp_push_subs") == "1", "D doppeltes Anmelden gibt keine zweite Zeile")
    nonce = lambda: L.psql("insert into sp_push_nonce default values returning nonce")
    st, j = rest("POST", "/rpc/sp_push_claim", {"p_nonce": "11111111-2222-4333-8444-555555555555"}); check(j == {"status": 401}, f"D falscher Einmal-Code: {j}")
    old_n = L.psql("insert into sp_push_nonce (created_at) values (now() - interval '6 minutes') returning nonce")
    st, j = rest("POST", "/rpc/sp_push_claim", {"p_nonce": old_n}); check(j == {"status": 401}, f"D abgelaufener Einmal-Code: {j}")
    n1 = nonce()
    st, j = rest("POST", "/rpc/sp_push_claim", {"p_nonce": n1}); check(j == {"status": 200, "keys": None, "due": []}, f"D ohne Schlüssel nichts fällig: {j}")
    st, j = rest("POST", "/rpc/sp_push_setkeys", {"p_nonce": "11111111-2222-4333-8444-555555555555", "p_pub": "B" * 87, "p_priv": "{}"}); check(j == {"status": 401}, f"D Schlüssel setzen ohne Code: {j}")
    st, j = rest("POST", "/rpc/sp_push_setkeys", {"p_nonce": n1, "p_pub": "B" * 87, "p_priv": '{"d":"geheim"}'}); check(j["status"] == 200 and j["keys"]["pub"] == "B" * 87, f"D Schlüssel setzen: {j}")
    st, j = rest("POST", "/rpc/sp_push_setkeys", {"p_nonce": n1, "p_pub": "C" * 87, "p_priv": "{}"}); check(j["keys"]["pub"] == "B" * 87, f"D Schlüssel werden nicht überschrieben: {j}")
    st, j = rest("POST", "/rpc/sp_push_public_key", {}, jwt=X); check(j == "B" * 87, f"D App bekommt den öffentlichen Schlüssel: {j}")
    check("geheim" not in json.dumps(j), "D privater Schlüssel sichtbar")
    now = int(_t.time() * 1000); H = 3600000
    proj = lambda pid, name, rat, **kw: {"id": pid, "name": name, "created": now, "paused": False, "finished": None, "remindAt": rat, "mod": now, "saves": [{"id": "s0", "at": now, "where": "", "next": "alt"}, {"id": "s1", "at": now, "where": "", "next": "Schritt von " + name}], **kw}
    data = {"v": 2, "deleted": {}, "projects": [
        proj("faellig", "Steuern", now - H), proj("zukunft", "Später", now + H), proj("alt", "Vorgestern", now - 50 * H),
        proj("ruht", "Ruht", now - H, paused=True), proj("fertig", "Fertig", now - H, finished=now), proj("ohne", "Ohne", None),
        {"id": "kaputt", "remindAt": "morgen"}, "unsinn", {"id": 5, "remindAt": now - H}]}
    rest("POST", "/sp_state", {"user_id": XID, "data": data, "updated_at": 1}, jwt=X, prefer="return=minimal")
    rest("PATCH", f"/sp_state?user_id=eq.{WID}", {"data": {"v": 2, "projects": [proj("fremd", "Von der Partnerin", now - H)]}}, jwt=W)
    rest("POST", "/sp_state", {"user_id": WID, "data": {"v": 2, "projects": [proj("fremd", "Von der Partnerin", now - H)]}, "updated_at": 1}, jwt=W, prefer="return=minimal")
    st, j = rest("POST", "/rpc/sp_push_claim", {"p_nonce": n1}); due = j.get("due", [])
    check(len(due) == 1 and due[0]["project"] == "faellig" and due[0]["name"] == "Steuern" and due[0]["next"] == "Schritt von Steuern" and due[0]["endpoint"] == EP and due[0]["remind"] == now - H, f"D genau die eine fällige Erinnerung: {due}")
    check(j["keys"]["priv"] == '{"d":"geheim"}', "D Funktion bekommt den privaten Schlüssel")
    st, j = rest("POST", "/rpc/sp_push_claim", {"p_nonce": n1}); check(j["due"] == [], f"D zweiter Lauf schickt nichts doppelt: {j['due']}")
    st, j = rest("POST", "/rpc/sp_push_report", {"p_nonce": "11111111-2222-4333-8444-555555555555", "p_gone": [due[0]["sub"]], "p_failed": []}); check(j == {"status": 401} and L.psql("select count(*) from sp_push_subs") == "1", "D Melden ohne Code ändert nichts")
    st, j = rest("POST", "/rpc/sp_push_report", {"p_nonce": n1, "p_gone": [], "p_failed": [{"sub": due[0]["sub"], "project": "faellig", "remind": now - H}]})
    st, j = rest("POST", "/rpc/sp_push_claim", {"p_nonce": n1}); check(len(j["due"]) == 1, f"D Fehlgeschlagenes kommt beim nächsten Lauf nochmals: {j['due']}")
    rest("POST", "/rpc/sp_push_subscribe", {"p_endpoint": EP + "-zwei", **KEYS}, jwt=X)
    st, j = rest("POST", "/rpc/sp_push_claim", {"p_nonce": n1}); check(len(j["due"]) == 1 and j["due"][0]["endpoint"] == EP + "-zwei", f"D zweites Gerät bekommt die Erinnerung auch, das erste nicht nochmals: {j['due']}")
    st, j = rest("POST", "/rpc/sp_push_unsubscribe", {"p_endpoint": EP}, jwt=W); check(L.psql("select count(*) from sp_push_subs") == "2", "D fremdes Gerät lässt sich nicht abmelden")
    st, j = rest("POST", "/rpc/sp_push_subscribe", {"p_endpoint": EP, **KEYS}, jwt=W)
    check(L.psql(f"select user_id from sp_push_subs where endpoint = '{EP}'") == WID and L.psql("select count(*) from sp_push_subs") == "2", "D Gerät wechselt zum neu angemeldeten Konto")
    st, j = rest("POST", "/rpc/sp_push_claim", {"p_nonce": n1}); check(len(j["due"]) == 1 and j["due"][0]["name"] == "Von der Partnerin", f"D nach dem Wechsel nur noch Erinnerungen des neuen Kontos: {j['due']}")
    gid = L.psql(f"select id from sp_push_subs where endpoint = '{EP}-zwei'")
    rest("POST", "/rpc/sp_push_report", {"p_nonce": n1, "p_gone": [gid], "p_failed": []}); check(L.psql("select count(*) from sp_push_subs") == "1" and L.psql(f"select count(*) from sp_push_sent where sub_id = '{gid}'") == "0", "D abgemeldetes Gerät wird entfernt")
    rest("POST", "/rpc/sp_push_unsubscribe", {"p_endpoint": EP}, jwt=W); check(L.psql("select count(*) from sp_push_subs") == "0", "D eigenes Gerät abmelden")
    # Probe ohne pg_net: wird vorgemerkt und kommt mit dem nächsten Lauf
    rest("POST", "/rpc/sp_push_subscribe", {"p_endpoint": EP, **KEYS}, jwt=X)
    st, j = rest("POST", "/rpc/sp_push_test", {"p_endpoint": EP}, jwt=W); check(j is False, f"D Probe für fremdes Gerät: {st} {j}")
    st, j = rest("POST", "/rpc/sp_push_test", {"p_endpoint": EP}); check(st in (401, 403), f"D Probe ohne Anmeldung ({st})")
    st, j = rest("POST", "/rpc/sp_push_test", {"p_endpoint": EP}, jwt=X); check(st == 200 and j is True, f"D Probe anfordern: {st} {j}")
    st, j = rest("POST", "/rpc/sp_push_test", {"p_endpoint": EP}, jwt=X); check(j is False, f"D zweite Probe innert 30 Sekunden abgelehnt: {j}")
    st, j = rest("POST", "/rpc/sp_push_claim", {"p_nonce": n1}); pr = [d for d in j["due"] if d["project"] == ""]
    check(len(pr) == 1 and pr[0]["endpoint"] == EP and "Probe" in pr[0]["text"] and pr[0]["name"] == "Speicherpunkt", f"D Probe wird ausgeliefert: {j['due']}")
    st, j = rest("POST", "/rpc/sp_push_claim", {"p_nonce": n1}); check(not [d for d in j["due"] if d["project"] == ""], "D Probe kommt nur einmal")
    rest("POST", "/rpc/sp_push_unsubscribe", {"p_endpoint": EP}, jwt=X)
    # Zeitplan (pg_net wird hier durch eine Attrappe ersetzt)
    L.psql("create schema if not exists net; create table if not exists net.calls (url text, body jsonb, headers jsonb); create or replace function net.http_post(url text, body jsonb, headers jsonb) returns bigint language sql as $$ insert into net.calls values (url, body, headers); select 1::bigint $$;")
    L.psql("select sp_push_tick()"); check(L.psql("select count(*) from net.calls") == "0", "D ohne Geräte kein Aufruf")
    rest("POST", "/rpc/sp_push_subscribe", {"p_endpoint": EP, **KEYS}, jwt=X); L.psql("select sp_push_tick()")
    call = json.loads(L.psql("select row_to_json(c)::text from net.calls c"))
    check(call["url"] == "https://satqwruqmwgcflcggbul.supabase.co/functions/v1/push" and "apikey" not in json.dumps(call["headers"]).lower(), f"D Aufruf der Funktion: {call}")
    st, j = rest("POST", "/rpc/sp_push_claim", {"p_nonce": call["body"]["nonce"]}); check(j["status"] == 200 and len(j["due"]) == 1, f"D Einmal-Code aus dem Zeitplan gilt: {j}")
    L.psql("truncate net.calls; update sp_push_subs set test_at = null"); st, j = rest("POST", "/rpc/sp_push_test", {"p_endpoint": EP}, jwt=X)
    check(j is True and L.psql("select count(*) from net.calls") == "1", f"D Probe löst den Versand sofort aus: {j}")
    check(L.psql("select count(*) from sp_push_nonce where created_at < now() - interval '1 hour'") == "0", "D alte Codes aufgeräumt")
    L.psql("truncate sp_push_keys; truncate net.calls; delete from sp_push_subs"); L.psql("select sp_push_tick()"); check(L.psql("select count(*) from net.calls") == "1", "D ohne Schlüssel läuft der Zeitplan trotzdem (legt sie an)")
    check("NICHT aktiv" in L.psql("select sp_push_zeitplan()"), "D Zeitplan meldet fehlende Erweiterung verständlich")
    rest("POST", "/rpc/sp_push_subscribe", {"p_endpoint": EP, **KEYS}, jwt=X)
    rest("POST", "/rpc/sp_delete_account", {}, jwt=X); check(L.psql("select count(*) from sp_push_subs") == "0", "D Konto löschen entfernt die Geräte")
    # Zählung
    DEV = "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"
    st, j = rest("POST", "/rpc/sp_seen", {"p_device": DEV}); check(st in (200, 204), f"D Zählung ohne Anmeldung ({st} {j})")
    rest("POST", "/rpc/sp_seen", {"p_device": DEV}); check(L.psql("select count(*) from sp_visits") == "1", "D ein Eintrag pro Gerät und Tag")
    st, j = rest("POST", "/rpc/sp_seen", {"p_device": "kein-uuid"}); check(st == 400, f"D kaputte Gerätenummer abgelehnt ({st})")
    L.psql("""truncate sp_visits; insert into sp_visits values
      ('00000000-0000-4000-8000-000000000001','2026-11-02'), ('00000000-0000-4000-8000-000000000001','2026-11-05'), ('00000000-0000-4000-8000-000000000001','2026-11-12'),
      ('00000000-0000-4000-8000-000000000002','2026-11-03'), ('00000000-0000-4000-8000-000000000002','2026-11-30'),
      ('00000000-0000-4000-8000-000000000003','2026-11-04'),
      ('00000000-0000-4000-8000-000000000004','2026-11-10'), ('00000000-0000-4000-8000-000000000004','2026-11-11')""")
    rows = L.psql("select startwoche || ':' || geraete || ':' || zurueck_in_woche_1 || ':' || zurueck_in_woche_2 || ':' || zurueck_spaeter from sp_wiederkehr order by startwoche").split("\n")
    check(rows == ["2026-11-02:3:1:1:1", "2026-11-09:1:1:0:0"], f"D Auswertung Wiederkehr: {rows}")

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
