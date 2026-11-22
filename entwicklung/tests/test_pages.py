"""Landingpage mit Warteliste, Datenschutz, Impressum, Konto löschen."""
import sys, json, pathlib, shutil, http.server, threading, functools
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
BASE = f"http://127.0.0.1:{web.server_address[1]}/"
api, S = mock_supabase.start()
API = f"http://127.0.0.1:{api.server_address[1]}"
for f in ["index.html", "willkommen/index.html"]:
    pth = SITE / f
    pth.write_text(pth.read_text(encoding="utf-8").replace("connect-src 'self' https://satqwruqmwgcflcggbul.supabase.co", "connect-src 'self' " + API), encoding="utf-8")
INIT = "window.SP_CONFIG = { url: %s, key: %s };" % (json.dumps(API), json.dumps(mock_supabase.KEY))
problems = []
def check(c, m):
    if not c: problems.append(m)
def watch(pg, name):
    pg._errs = []
    pg.on("pageerror", lambda e: pg._errs.append(name + ": " + str(e)))
    pg.on("console", lambda m: pg._errs.append(name + " console: " + m.text) if m.type == "error" and "Failed to load resource" not in m.text else None)
    return pg
def overflow(pg): return pg.evaluate("document.documentElement.scrollWidth > window.innerWidth + 1")

with sync_playwright() as p:
    b = p.chromium.launch()
    # 1. Aussehen und Grundfunktionen der Seiten, verschiedene Breiten und Farben
    for w, h, scheme in [(320, 640, "light"), (390, 844, "dark"), (1280, 900, "light")]:
        ctx = b.new_context(viewport={"width": w, "height": h}, color_scheme=scheme); ctx.add_init_script(INIT)
        pg = watch(ctx.new_page(), f"pages{w}")
        for path, must in [("willkommen/", "Den Faden"), ("datenschutz.html", "Datenschutz"), ("impressum.html", "Impressum")]:
            pg.goto(BASE + path); pg.wait_for_timeout(300)
            body = pg.text_content("body")
            check(must.replace(" ", "") in body.replace(" ", ""), f"{path} @{w}: heading missing")
            check(not overflow(pg), f"{path} @{w}: horizontal overflow")
            ext = pg.evaluate("performance.getEntriesByType('resource').map(e => e.name).filter(n => !n.startsWith(location.origin))")
            check(not ext, f"{path} @{w}: external requests {ext}")
            fonts = pg.evaluate("document.fonts.check('16px Lora') && document.fonts.check('16px Inter')")
            check(fonts, f"{path} @{w}: fonts not loaded")
            pg.screenshot(path=str(OUT / f"{path.strip('/').replace('.html', '').replace('/', '_') or 'root'}_{w}_{scheme}.png"), full_page=True)
        problems.extend(pg._errs); ctx.close()

    # 2. Warteliste
    ctx = b.new_context(viewport={"width": 390, "height": 844}); ctx.add_init_script(INIT)
    pg = watch(ctx.new_page(), "waitlist")
    pg.goto(BASE + "willkommen/?q=instagram"); pg.wait_for_timeout(200)
    pg.click("text=Auf die Warteliste"); pg.wait_for_timeout(1500)
    check(pg.evaluate("document.getElementById('warteliste').getBoundingClientRect().top < 200"), "anchor link did not scroll to waitlist")
    pg.fill("#wl-email", "keine-mail"); pg.click("#wl-submit")
    check("gültige" in pg.text_content("#wl-status") and pg.get_attribute("#wl-email", "aria-invalid") == "true", "invalid email accepted")
    pg.fill("#wl-email", "  Test.Person@Example.CH "); pg.fill("#wl-note", "Nach einer Pause wieder anfangen.")
    pg.click("#wl-submit"); pg.wait_for_timeout(500)
    check("eingetragen" in pg.text_content("#wl-status"), "success message missing: " + pg.text_content("#wl-status"))
    check(S.waitlist and S.waitlist[-1] == {"email": "test.person@example.ch", "note": "Nach einer Pause wieder anfangen.", "source": "instagram"}, "waitlist entry wrong: %s" % S.waitlist)
    check(not pg.locator("#wl-email").is_visible(), "form fields still visible after success")
    pg.screenshot(path=str(OUT / "waitlist_done.png"), full_page=True)
    pg.reload(); pg.wait_for_timeout(200)
    pg.fill("#wl-email", "test.person@example.ch"); pg.click("#wl-submit"); pg.wait_for_timeout(400)
    check("schon" in pg.text_content("#wl-status"), "duplicate not handled")
    pg.reload(); pg.wait_for_timeout(200)
    n = len(S.waitlist)
    pg.evaluate("document.getElementById('wl-website').value = 'spam.example'"); pg.fill("#wl-email", "bot@spam.example"); pg.click("#wl-submit"); pg.wait_for_timeout(300)
    check(len(S.waitlist) == n, "honeypot entry was stored")
    pg.reload(); pg.wait_for_timeout(200)
    S.waitlist_status = 500
    pg.fill("#wl-email", "neu@example.ch"); pg.click("#wl-submit"); pg.wait_for_timeout(400)
    check("nicht geklappt" in pg.text_content("#wl-status") and pg.is_enabled("#wl-submit"), "server error not handled")
    S.waitlist_status = 0
    ctx.set_offline(True); pg.click("#wl-submit"); pg.wait_for_timeout(400)
    check("Keine Verbindung" in pg.text_content("#wl-status"), "offline not handled")
    ctx.set_offline(False)
    problems.extend(pg._errs); ctx.close()

    # 3. Verlinkung App <-> Seiten
    ctx = b.new_context(viewport={"width": 390, "height": 844}); ctx.add_init_script(INIT)
    pg = watch(ctx.new_page(), "links")
    pg.goto(BASE); pg.wait_for_timeout(300)
    pg.click("button:has-text('Einstellungen')")
    check(pg.locator("nav.legal a").count() == 3, "legal links missing in settings")
    pg.click("nav.legal >> text=Datenschutz"); pg.wait_for_timeout(300)
    check(pg.url.endswith("/datenschutz.html"), "datenschutz link wrong: " + pg.url)
    check(pg.locator("mark.todo").count() == 0 and "BITTE" not in pg.text_content("body"), "Platzhalter in der Datenschutzerklärung noch offen")
    pg.click("footer >> text=Impressum"); pg.wait_for_timeout(200)
    check(pg.url.endswith("/impressum.html"), "impressum link wrong")
    pg.click("footer >> text=Über Speicherpunkt"); pg.wait_for_timeout(200)
    check(pg.url.endswith("/willkommen/"), "landing link wrong: " + pg.url)
    pg.click("header >> text=App öffnen"); pg.wait_for_timeout(300)
    check("Ein Schritt" in pg.text_content("main"), "app link from landing wrong")
    problems.extend(pg._errs); ctx.close()

    # 4. Konto löschen
    ctx = b.new_context(viewport={"width": 390, "height": 844}); ctx.add_init_script(INIT)
    pg = watch(ctx.new_page(), "delete")
    pg.goto(BASE); pg.wait_for_timeout(200)
    pg.click("button:has-text('Einstellungen')"); pg.click("text=Neues Konto erstellen")
    pg.fill("#f-email", "weg@example.ch"); pg.fill("#f-pass", "secret1"); pg.click("#account button[type=submit]"); pg.wait_for_timeout(700)
    pg.click("text=+ Neues Projekt"); pg.fill("#f-name", "Wird gelöscht"); pg.fill("#f-next", "x"); pg.click("button[type=submit]"); pg.wait_for_timeout(1600)
    check("weg@example.ch" in S.users and S.rows, "setup for delete failed")
    pg.click("button:has-text('Einstellungen')"); pg.click("[data-action=delete-account]")
    check(pg.locator("#delete-box").is_visible(), "delete confirmation missing")
    pg.screenshot(path=str(OUT / "delete_confirm.png"), full_page=True)
    pg.fill("#f-delete", "ja"); pg.click("[data-action=delete-account-yes]")
    check(pg.locator("#delete-err").is_visible() and "weg@example.ch" in S.users, "delete without typing löschen not blocked")
    pg.click("text=Abbrechen")
    check(pg.locator("#delete-box").count() == 0, "cancel did not close delete box")
    pg.click("[data-action=delete-account]"); pg.fill("#f-delete", "Löschen"); pg.click("[data-action=delete-account-yes]"); pg.wait_for_timeout(700)
    check("weg@example.ch" not in S.users and not S.rows, "account not deleted on server")
    check("gelöscht" in pg.text_content("#toast"), "delete toast missing")
    check(pg.locator("#examples-note").is_visible() and "Wird gelöscht" not in pg.text_content("main"), "local data not cleared after delete")
    check(pg.evaluate("localStorage.getItem('speicherpunkt.session')") is None, "session not cleared after delete")
    problems.extend(pg._errs); ctx.close()

    # 5. Die Schnittstelle aus Version 8 ist weg, auch mit Konto
    ctx = b.new_context(viewport={"width": 390, "height": 844}); ctx.add_init_script(INIT)
    pg = watch(ctx.new_page(), "noapi")
    pg.goto(BASE); pg.wait_for_timeout(200)
    pg.click("button:has-text('Einstellungen')"); pg.click("text=Neues Konto erstellen")
    pg.fill("#f-email", "ohne@example.ch"); pg.fill("#f-pass", "secret1"); pg.click("#account button[type=submit]"); pg.wait_for_timeout(700)
    pg.click("button:has-text('Einstellungen')")
    check(pg.locator("#api").count() == 0 and "Schnittstelle" not in pg.text_content("main") and "Token" not in pg.text_content("main"), "Schnittstelle noch in den Einstellungen")
    check("Version 10" in pg.text_content("#version"), "Versionsnummer: " + pg.text_content("#version"))
    problems.extend(pg._errs); ctx.close()
    b.close()
print(json.dumps(problems, ensure_ascii=False, indent=1) if problems else "ALL OK")
