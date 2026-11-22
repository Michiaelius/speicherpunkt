"""Robustheit: kaputte Daten, verschwundene Projekte, sicheres Abmelden, Token in zwei Tabs."""
import sys, json, pathlib, shutil, time, http.server, threading, functools
sys.path.insert(0, str(pathlib.Path(__file__).parent))
from playwright.sync_api import sync_playwright
import mock_supabase

OUT = pathlib.Path(sys.argv[2]); OUT.mkdir(parents=True, exist_ok=True)
SITE = OUT / "site"
if SITE.exists(): shutil.rmtree(SITE)
shutil.copytree(sys.argv[1], SITE)
class Q(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a): pass
web = http.server.ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(Q, directory=str(SITE.resolve())))
threading.Thread(target=web.serve_forever, daemon=True).start()
URL = f"http://127.0.0.1:{web.server_address[1]}/index.html"
api, S = mock_supabase.start()
API = f"http://127.0.0.1:{api.server_address[1]}"
idx = SITE / "index.html"
idx.write_text(idx.read_text(encoding="utf-8").replace("connect-src 'self' https://satqwruqmwgcflcggbul.supabase.co", "connect-src 'self' " + API), encoding="utf-8")
INIT = "window.SP_CONFIG = { url: %s, key: %s };" % (json.dumps(API), json.dumps(mock_supabase.KEY))

problems = []
def check(c, m):
    if not c: problems.append(m)
def txt(pg): return pg.text_content("main")
def watch(pg, name):
    pg._errs = []
    pg.on("pageerror", lambda e: pg._errs.append(name + ": " + str(e)))
    pg.on("console", lambda m: pg._errs.append(name + " console: " + m.text) if m.type == "error" and "Failed to load resource" not in m.text else None)

with sync_playwright() as p:
    b = p.chromium.launch()

    # 1. kaputte Daten im Speicher
    ctx = b.new_context(); ctx.add_init_script(INIT); pg = ctx.new_page(); watch(pg, "corrupt")
    pg.goto(URL); pg.wait_for_timeout(200)
    pg.evaluate("""localStorage.setItem('speicherpunkt.v1', JSON.stringify({v:2, projects:[
      {id:'a', name:'Gut', created: Date.now(), saves:[{id:'s', at: Date.now(), next:'Weiter'}]},
      {id:'b', name:'', saves:'kaputt'},
      {name:'ohne id', saves:[]},
      {id:'c', name:'Mit kaputtem Schritt', saves:[{at:'gestern'}, {next:'Echter Schritt', at: 5}]},
      null, 42, {id:'a', name:'Doppelt', saves:[]}
    ], deleted: []}))""")
    pg.reload(); pg.wait_for_timeout(300)
    t = txt(pg)
    check("Gut" in t and "Echter Schritt" in t and "Ohne Namen" in t, "corrupt data not rendered sensibly: " + t[:300])
    check("Jahren" not in t, "nonsense timestamp shown as years ago")
    check("Doppelt" not in t, "duplicate id not removed")
    pg.click("[data-action=open][data-id=b] >> nth=0"); pg.wait_for_timeout(100)
    check("Noch kein Speicherpunkt" in txt(pg), "project without saves not handled")
    pg.click("button:has-text('Übersicht')")
    # kaputte Sicherung einfügen
    pg.click("button:has-text('Einstellungen')")
    pg.fill("#f-import", '{"projects": [1, 2, "x"]}'); pg.click("text=Einfügen und ersetzen")
    check(pg.locator("#imp-err").is_visible(), "malformed backup accepted")
    for e in pg._errs: problems.append(e)
    ctx.close()

    # 2. Projekt verschwindet, während es offen ist
    ctx = b.new_context(); ctx.add_init_script(INIT); pg = ctx.new_page(); watch(pg, "vanish")
    pg.goto(URL); pg.wait_for_timeout(200)
    pg.click("text=+ Neues Projekt"); pg.fill("#f-name", "Weg"); pg.fill("#f-next", "Schritt"); pg.click("button[type=submit]")
    pg.get_by_role("button", name="Weitermachen", exact=True).click()
    pg.evaluate("""() => { const s = JSON.parse(localStorage.getItem('speicherpunkt.v1')); s.projects = []; localStorage.setItem('speicherpunkt.v1', JSON.stringify(s)); }""")
    # Seite neu laden ist nicht nötig: wir simulieren einen Abgleich, der das Projekt entfernt, über ein storage-Event aus einem zweiten Tab
    pg2 = ctx.new_page(); pg2.goto(URL); pg2.wait_for_timeout(200)
    pg2.evaluate("""() => { const s = JSON.parse(localStorage.getItem('speicherpunkt.v1')); s.updated = Date.now(); localStorage.setItem('speicherpunkt.v1', JSON.stringify(s)); }""")
    pg.wait_for_timeout(300)
    if pg.locator("text=Ich fange an").count():
        pg.click("text=Ich fange an")
        check("gibt es nicht mehr" in pg.text_content("#toast") or "Neues Projekt" in txt(pg), "vanished project: no graceful handling")
    else:
        check("Neues Projekt" in txt(pg), "vanished project: view not reset to home")
    for e in pg._errs: problems.append(e)
    ctx.close()

    # 3. Abmelden mit nicht abgeglichenen Änderungen
    ctx = b.new_context(); ctx.add_init_script(INIT); pg = ctx.new_page(); watch(pg, "logout")
    pg.goto(URL); pg.wait_for_timeout(200)
    pg.click("button:has-text('Einstellungen')"); pg.click("text=Neues Konto erstellen")
    pg.fill("#f-email", "a@b.ch"); pg.fill("#f-pass", "secret1"); pg.click("#account button[type=submit]"); pg.wait_for_timeout(700)
    S.down = True
    pg.click("text=+ Neues Projekt"); pg.fill("#f-name", "Unterwegs"); pg.fill("#f-next", "Ohne Netz"); pg.click("button[type=submit]"); pg.wait_for_timeout(1600)
    pg.click("button:has-text('Einstellungen')"); pg.click("text=Abmelden"); pg.click("button:has-text('Abmelden') >> nth=0"); pg.wait_for_timeout(800)
    check(pg.locator("#logout-warn").is_visible(), "no warning when logging out with unsynced changes")
    check(pg.locator("#acc-email").count() == 1, "logged out despite unsynced changes")
    pg.screenshot(path=str(OUT / "logout_warn.png"), full_page=True)
    S.down = False
    pg.click("text=Nochmals abgleichen"); pg.wait_for_timeout(800)
    uid = next(iter(S.rows))
    check(any(x["name"] == "Unterwegs" for x in S.rows[uid]["data"]["projects"]), "unsynced project not uploaded after retry")
    check(pg.locator("#logout-warn").count() == 0, "warning stays after successful sync")
    pg.click("button:has-text('Abmelden') >> nth=0"); pg.wait_for_timeout(800)
    check(pg.locator("#acc-email").count() == 0, "normal logout failed")
    for e in pg._errs: problems.append(e)
    ctx.close()

    # 4. Zwei Tabs, Anmeldung wird erneuert
    S.expires_in = 75
    ctx = b.new_context(); ctx.add_init_script(INIT); t1 = ctx.new_page(); watch(t1, "tab1")
    t1.goto(URL); t1.wait_for_timeout(200)
    t1.click("button:has-text('Einstellungen')"); t1.click("text=Neues Konto erstellen")
    t1.fill("#f-email", "tabs@b.ch"); t1.fill("#f-pass", "secret1"); t1.click("#account button[type=submit]"); t1.wait_for_timeout(700)
    t2 = ctx.new_page(); watch(t2, "tab2"); t2.goto(URL); t2.wait_for_timeout(500)
    time.sleep(16.5)   # beide Sitzungen brauchen jetzt eine Erneuerung
    t1.evaluate("document.dispatchEvent(new Event('visibilitychange'))"); t1.wait_for_timeout(800)
    t2.evaluate("document.dispatchEvent(new Event('visibilitychange'))"); t2.wait_for_timeout(800)
    for tab in (t1, t2):
        tab.click("button:has-text('Einstellungen')") if tab.locator("button:has-text('Einstellungen')").count() else None
        tab.wait_for_timeout(100)
    check(t1.locator("#acc-email").count() == 1, "tab1 lost its login after refresh in two tabs")
    check(t2.locator("#acc-email").count() == 1, "tab2 lost its login after refresh in two tabs")
    refreshes = [c for c in S.calls if c[1].startswith("/auth/v1/token?grant_type=refresh_token")]
    check(len(refreshes) == 1, "expected exactly one token refresh, got %d" % len(refreshes))
    S.expires_in = 3600
    for tab in (t1, t2): problems.extend(tab._errs)
    b.close()
print(json.dumps(problems, ensure_ascii=False, indent=1) if problems else "ALL OK")
