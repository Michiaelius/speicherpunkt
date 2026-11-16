"""Passwort vergessen, neues Passwort, Links aus E-Mails."""
import sys, json, pathlib, shutil, http.server, threading, functools, urllib.parse
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

with sync_playwright() as p:
    b = p.chromium.launch()
    ctx = b.new_context(viewport={"width": 390, "height": 844}); ctx.add_init_script(INIT); pg = ctx.new_page(); errs = []
    pg.on("pageerror", lambda e: errs.append(str(e)))
    pg.on("console", lambda m: errs.append(m.text) if m.type == "error" and "Failed to load resource" not in m.text else None)
    pg.goto(URL); pg.wait_for_timeout(200)
    pg.click("button:has-text('Einstellungen')"); pg.click("text=Neues Konto erstellen")
    pg.fill("#f-email", "frau@example.ch"); pg.fill("#f-pass", "altes123"); pg.click("#account button[type=submit]"); pg.wait_for_timeout(700)
    pg.click("button:has-text('Einstellungen')"); pg.click("text=Abmelden"); pg.click("button:has-text('Abmelden') >> nth=0"); pg.wait_for_timeout(600)

    # 1. Passwort vergessen
    pg.click("text=Passwort vergessen?")
    check("Passwort zurücksetzen" in pg.text_content("#account"), "reset form missing")
    pg.fill("#f-email", "frau@example.ch"); pg.click("#account button[type=submit]"); pg.wait_for_timeout(500)
    check(pg.locator("#auth-info").is_visible() and "E-Mail unterwegs" in pg.text_content("#auth-info"), "reset info missing")
    check(S.recover and S.recover[-1]["email"] == "frau@example.ch" and S.recover[-1]["redirect_to"].endswith("/index.html"), "recover call wrong: %s" % S.recover)
    pg.screenshot(path=str(OUT / "01_reset.png"), full_page=True)
    pg.click("text=Zurück zur Anmeldung")
    check("Anmelden" in pg.text_content("#account h2"), "back to login failed")

    # 2. Link aus der E-Mail -> neues Passwort setzen
    uid = S.users["frau@example.ch"]["id"]
    sess = mock_supabase.session_for(uid, "frau@example.ch")
    link = URL + "#" + urllib.parse.urlencode({"access_token": sess["access_token"], "refresh_token": sess["refresh_token"], "expires_in": 3600, "token_type": "bearer", "type": "recovery"})
    pg.goto(link); pg.wait_for_timeout(700)
    check(pg.locator("#f-newpass").count() == 1, "new password form missing after recovery link")
    check("access_token" not in pg.url, "token still in address bar: " + pg.url)
    pg.screenshot(path=str(OUT / "02_newpass.png"), full_page=True)
    pg.fill("#f-newpass", "altes123"); pg.click("#account button[type=submit]"); pg.wait_for_timeout(400)
    check("unterscheiden" in pg.text_content("#auth-err"), "same password message missing")
    pg.fill("#f-newpass", "neues456"); pg.click("#account button[type=submit]"); pg.wait_for_timeout(500)
    check("Neues Passwort gespeichert" in pg.text_content("#toast"), "new password toast missing")
    check(S.users["frau@example.ch"]["password"] == "neues456", "password not changed on server")
    pg.click("button:has-text('Einstellungen')")
    check(pg.locator("#acc-email").count() == 1, "not signed in after setting new password")
    pg.click("text=Abmelden"); pg.click("button:has-text('Abmelden') >> nth=0"); pg.wait_for_timeout(600)
    pg.fill("#f-email", "frau@example.ch"); pg.fill("#f-pass", "altes123"); pg.click("#account button[type=submit]"); pg.wait_for_timeout(500)
    check("stimmt nicht" in pg.text_content("#auth-err"), "old password still works")
    pg.fill("#f-pass", "neues456"); pg.click("#account button[type=submit]"); pg.wait_for_timeout(700)
    check("Angemeldet" in pg.text_content("#toast"), "login with new password failed")

    # 3. abgelaufener Link
    ctx2 = b.new_context(viewport={"width": 390, "height": 844}); ctx2.add_init_script(INIT); pg2 = ctx2.new_page()
    pg2.on("pageerror", lambda e: errs.append("pg2: " + str(e)))
    pg2.goto(URL + "#error=access_denied&error_code=otp_expired&error_description=Email+link+is+invalid+or+has+expired"); pg2.wait_for_timeout(500)
    check("abgelaufen" in (pg2.text_content("#auth-err") or ""), "expired link message missing")
    check("Passwort zurücksetzen" in pg2.text_content("#account h2"), "expired link should show reset form")
    check("error=" not in pg2.url, "error still in address bar")

    # 4. Bestätigungslink nach Registrierung meldet direkt an
    S.users["neu@example.ch"] = {"id": "u-neu", "password": "abcdef1"}
    s2 = mock_supabase.session_for("u-neu", "neu@example.ch")
    pg2.goto(URL + "#" + urllib.parse.urlencode({"access_token": s2["access_token"], "refresh_token": s2["refresh_token"], "expires_in": 3600, "type": "signup"})); pg2.wait_for_timeout(700)
    check("Angemeldet" in (pg2.text_content("#toast") or ""), "signup link did not sign in")
    pg2.click("button:has-text('Einstellungen')")
    check("neu@example.ch" in (pg2.text_content("#acc-email") or ""), "signup link: wrong account")
    # 4b. Link für eine andere Person auf einem Gerät, auf dem schon jemand angemeldet ist
    pg2.click("button:has-text('Übersicht')"); pg2.click("text=+ Neues Projekt"); pg2.fill("#f-name", "Projekt von Neu"); pg2.fill("#f-next", "x"); pg2.click("button[type=submit]"); pg2.wait_for_timeout(1500)
    uid_f = S.users["frau@example.ch"]["id"]; s3 = mock_supabase.session_for(uid_f, "frau@example.ch")
    pg2.goto(URL + "#" + urllib.parse.urlencode({"access_token": s3["access_token"], "refresh_token": s3["refresh_token"], "expires_in": 3600, "type": "magiclink"})); pg2.wait_for_timeout(1200)
    check("Projekt von Neu" not in pg2.text_content("main"), "other person's local projects shown after link login")
    check(not any(x["name"] == "Projekt von Neu" for x in S.rows.get(uid_f, {"data": {"projects": []}})["data"]["projects"]), "other person's projects uploaded into wrong account")
    # 5. kaputter Link
    ctx3 = b.new_context(); ctx3.add_init_script(INIT); pg3 = ctx3.new_page(); pg3.on("pageerror", lambda e: errs.append("pg3: " + str(e)))
    pg3.goto(URL + "#access_token=falsch&refresh_token=falsch&type=recovery"); pg3.wait_for_timeout(600)
    check("nicht geklappt" in (pg3.text_content("#auth-err") or ""), "bad link not handled")
    problems.extend(errs)
    b.close()
print(json.dumps(problems, ensure_ascii=False, indent=1) if problems else "ALL OK")
