import sys, json, pathlib, shutil, re, time, http.server, threading, functools, socket
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
_idx = SITE / "index.html"
_idx.write_text(_idx.read_text(encoding="utf-8").replace("connect-src 'self' https://satqwruqmwgcflcggbul.supabase.co", "connect-src 'self' " + API), encoding="utf-8")
INIT = "window.SP_CONFIG = { url: %s, key: %s };" % (json.dumps(API), json.dumps(mock_supabase.KEY))

problems = []
def check(c, m):
    if not c: problems.append(m)

def device(b, name, mobile=True):
    ctx = b.new_context(viewport={"width": 390, "height": 844} if mobile else {"width": 1200, "height": 900}, locale="de-CH", timezone_id="Europe/Zurich")
    ctx.add_init_script(INIT)
    pg = ctx.new_page(); pg._errs = []
    pg.on("pageerror", lambda e: pg._errs.append(name + ": " + str(e)))
    pg.on("console", lambda m: pg._errs.append(name + " console: " + m.text) if m.type == "error" and "ERR_" not in m.text and "Failed to load resource" not in m.text else None)
    pg.goto(URL); pg.wait_for_timeout(300)
    return ctx, pg

def txt(pg): return pg.text_content("main")

def new_project(pg, name, step):
    pg.click("text=+ Neues Projekt"); pg.fill("#f-name", name); pg.fill("#f-next", step); pg.click("button[type=submit]"); pg.wait_for_timeout(100)

def login(pg, email, pw, signup=False):
    pg.click("button:has-text('Einstellungen')")
    if signup: pg.click("text=Neues Konto erstellen")
    pg.fill("#f-email", email); pg.fill("#f-pass", pw)
    pg.click("#account button[type=submit]"); pg.wait_for_timeout(700)

def wait_sync(pg, ms=1800): pg.wait_for_timeout(ms)

with sync_playwright() as p:
    b = p.chromium.launch()
    phone_ctx, phone = device(b, "phone")
    pc_ctx, pc = device(b, "pc", mobile=False)

    # 1. phone: local project before having an account, then sign up -> uploaded
    new_project(phone, "Speicherpunkt-App", "Supabase testen")
    check(phone.locator("#login-hint").is_visible(), "login hint missing on home")
    phone.screenshot(path=str(OUT / "01_phone_home.png"), full_page=True)
    login(phone, "michael@example.ch", "geheim123", signup=True)
    check("Angemeldet" in phone.text_content("#toast") or "abgeglichen" in phone.text_content("#toast"), "signup toast missing: " + phone.text_content("#toast"))
    uid = next(iter(S.rows), None)
    check(uid and any(pr["name"] == "Speicherpunkt-App" for pr in S.rows[uid]["data"]["projects"]), "local project not uploaded at signup")
    check(phone.locator("#login-hint").count() == 0, "login hint still visible when signed in")

    # 2. pc: sign in -> sees phone project
    login(pc, "michael@example.ch", "falsch99")
    check("stimmt nicht" in pc.text_content("#auth-err"), "wrong password message missing")
    pc.screenshot(path=str(OUT / "02_pc_wrongpw.png"), full_page=True)
    pc.fill("#f-pass", "geheim123"); pc.click("#account button[type=submit]"); pc.wait_for_timeout(800)
    check("Supabase testen" in txt(pc), "pc does not show phone project after login")
    check(pc.locator("#examples-note").count() == 0, "pc still shows examples")
    pc.screenshot(path=str(OUT / "03_pc_after_login.png"), full_page=True)

    # 3. pc edits -> phone receives on sync
    new_project(pc, "Steuern", "Lohnausweis suchen"); wait_sync(pc)
    phone.evaluate("document.dispatchEvent(new Event('visibilitychange'))"); wait_sync(phone)
    check("Steuern" in txt(phone), "phone did not receive pc project")

    # 4. concurrent edits on different projects merge
    phone.click(".proj:has-text('Steuern')") if phone.locator(".proj:has-text('Steuern')").count() else phone.get_by_role("button", name="Weitermachen", exact=True).click()
    phone.click("text=Schritt kleiner machen"); phone.fill("#f-step", "Nur den Ordner Steuern öffnen"); phone.click("text=Übernehmen")
    pc.click(".proj:has-text('Speicherpunkt-App')") if pc.locator(".proj:has-text('Speicherpunkt-App')").count() else pc.get_by_role("button", name="Weitermachen", exact=True).click()
    pc.click("text=Mehr"); pc.click("button:has-text('Abschliessen')")
    wait_sync(phone); wait_sync(pc)
    for d in (phone, pc):
        d.evaluate("document.dispatchEvent(new Event('visibilitychange'))")
    wait_sync(phone); wait_sync(pc)
    for name, d in (("phone", phone), ("pc", pc)):
        d.click("button:has-text('Übersicht')") if d.locator("button:has-text('Übersicht')").count() else None
        d.wait_for_timeout(200)
        t = txt(d)
        check("Nur den Ordner Steuern öffnen" in t, name + ": phone edit lost in merge")
        check("Abgeschlossen (1)" in t, name + ": pc finish lost in merge")

    # 5. deletion propagates
    pc.click(".proj:has-text('Steuern')") if pc.locator(".proj:has-text('Steuern')").count() else pc.get_by_role("button", name="Weitermachen", exact=True).click()
    pc.click("text=Mehr"); pc.click("button:has-text('Löschen')"); pc.click("text=Ja, löschen"); wait_sync(pc)
    phone.evaluate("document.dispatchEvent(new Event('visibilitychange'))"); wait_sync(phone)
    check("Steuern" not in txt(phone), "deletion did not propagate to phone")

    # 6. offline edit on phone, later synced
    S.down = True
    new_project(phone, "Offline-Projekt", "Später abgleichen"); wait_sync(phone)
    phone.click("button:has-text('Einstellungen')")
    check("Offline" in phone.text_content("#sync-status"), "offline status not shown: " + phone.text_content("#sync-status"))
    phone.screenshot(path=str(OUT / "04_phone_offline.png"), full_page=True)
    S.down = False
    phone.click("text=Jetzt abgleichen"); wait_sync(phone)
    check("Abgeglichen" in phone.text_content("#sync-status"), "sync status after recovery wrong: " + phone.text_content("#sync-status"))
    pc.evaluate("document.dispatchEvent(new Event('visibilitychange'))"); wait_sync(pc)
    check("Offline-Projekt" in txt(pc), "offline edit never reached pc")

    # 7. token refresh
    S.expires_in = 30  # tokens issued from now are already 'about to expire' (<60s)
    for k in list(S.tokens): S.tokens[k] = (S.tokens[k][0], time.time() - 1)
    phone.evaluate("""()=>{const s=JSON.parse(localStorage.getItem('speicherpunkt.session'));s.expires_at=Date.now()-1000;localStorage.setItem('speicherpunkt.session',JSON.stringify(s));}""")
    phone.reload(); phone.wait_for_timeout(1500)
    check(any(c[1].startswith("/auth/v1/token?grant_type=refresh_token") for c in S.calls), "refresh not attempted")
    phone.click("button:has-text('Einstellungen')")
    check(phone.locator("#acc-email").count() == 1, "signed out after token refresh")
    S.expires_in = 3600

    # 8. wife: own account, sees nothing of michael
    wife_ctx, wife = device(b, "wife")
    check(wife.locator("#examples-note").is_visible(), "wife should start with examples")
    login(wife, "partnerin@example.ch", "sonne123", signup=True)
    t = txt(wife)
    check("Offline-Projekt" not in t and "Speicherpunkt-App" not in t, "wife sees michael's projects")
    new_project(wife, "Kundin Webseite", "Entwurf schicken"); wait_sync(wife)
    pc.evaluate("document.dispatchEvent(new Event('visibilitychange'))"); wait_sync(pc)
    check("Kundin Webseite" not in txt(pc), "michael sees wife's project")
    check(len(S.rows) == 2, "expected two separate user rows, got %d" % len(S.rows))
    wife.screenshot(path=str(OUT / "05_wife.png"), full_page=True)

    # 9. duplicate signup + logout clears device
    wife.click("button:has-text('Einstellungen')"); wife.click("text=Abmelden")
    check("verschwinden deine Projekte" in txt(wife), "logout confirm missing")
    wife.click("button:has-text('Abmelden') >> nth=0"); wife.wait_for_timeout(800)
    wife.click("button:has-text('Übersicht')"); wife.wait_for_timeout(100)
    check(wife.locator("#examples-note").is_visible() and "Kundin Webseite" not in txt(wife), "logout did not clear device")
    login(wife, "partnerin@example.ch", "sonne123", signup=True)
    check("schon ein Konto" in wife.text_content("#auth-err"), "duplicate signup message missing")
    wife.click("text=Ich habe schon ein Konto"); wife.fill("#f-pass", "sonne123"); wife.click("#account button[type=submit]"); wife.wait_for_timeout(800)
    check("Kundin Webseite" in txt(wife), "wife data not restored after re-login")
    pc.click("button:has-text('Einstellungen')")
    pc.screenshot(path=str(OUT / "06_pc_settings.png"), full_page=True)
    check(not pc.evaluate("document.documentElement.scrollWidth > window.innerWidth + 1"), "pc overflow")
    check(not phone.evaluate("document.documentElement.scrollWidth > window.innerWidth + 1"), "phone overflow")


    # 10. Vorschläge
    # a) ohne Konto: allgemeine Ideen im Formular für ein neues Projekt
    guest_ctx, guest = device(b, "guest")
    guest.click("text=+ Neues Projekt"); guest.fill("#f-name", "Keller räumen")
    guest.click("text=Schritt vorschlagen"); guest.wait_for_timeout(200)
    check(guest.locator(".sugg").count() == 3, "guest: 3 fallback ideas expected")
    check("Allgemeine Ideen" in guest.text_content(".sugg-note"), "guest: fallback note missing")
    check("«Keller räumen»" in guest.text_content(".sugg-list"), "guest: fallback ignores project name")
    guest.click(".sugg >> nth=1")
    check(guest.input_value("#f-next") == "Drei Stichworte notieren, was zu tun ist", "guest: pick did not fill input: " + guest.input_value("#f-next"))
    check(guest.input_value("#f-name") == "Keller räumen", "guest: name lost after suggestion")
    guest.click("button[type=submit]"); guest.wait_for_timeout(100)
    check("Drei Stichworte notieren" in txt(guest), "guest: picked step not saved")
    # b) mit Konto: KI-Vorschläge nach "Geschafft", mit Verlauf und Stand
    pc.click("button:has-text('Übersicht')") if pc.locator("button:has-text('Übersicht')").count() else None
    pc.get_by_role("button", name="Weitermachen", exact=True).click()
    pc.click("text=Ich fange an"); pc.click("text=Geschafft")
    pc.fill("#f-where", "Zwei Kisten sind schon weg.")
    pc.click("text=Schritt vorschlagen"); pc.wait_for_timeout(500)
    check(pc.locator(".sugg").count() == 3 and "KI-Weiter (done)" in pc.text_content(".sugg-list"), "pc: AI suggestions missing: " + pc.text_content(".sugg-list"))
    sb = S.suggest_bodies[-1] if S.suggest_bodies else {}
    check(sb.get("mode") == "done" and sb.get("where") == "Zwei Kisten sind schon weg." and len(sb.get("history", [])) >= 1 and sb.get("project"), "pc: request body incomplete: " + json.dumps(sb, ensure_ascii=False))
    check(pc.locator(".sugg-note").count() == 0, "pc: fallback note shown for AI result")
    check(pc.input_value("#f-where") == "Zwei Kisten sind schon weg.", "pc: typed text lost")
    pc.screenshot(path=str(OUT / "07_pc_suggest.png"), full_page=True)
    pc.click(".sugg >> nth=0"); pc.click("button[type=submit]"); pc.wait_for_timeout(200)
    check("KI-Mini:" in txt(pc), "pc: AI pick not saved")
    # c) Schritt kleiner machen
    pc.get_by_role("button", name="Weitermachen", exact=True).click()
    pc.click("text=Schritt kleiner machen"); pc.click("text=Kleinere Schritte vorschlagen"); pc.wait_for_timeout(500)
    sb = S.suggest_bodies[-1]
    check(sb.get("mode") == "smaller" and sb.get("step", "").startswith("KI-Mini"), "smaller: wrong body " + json.dumps(sb, ensure_ascii=False))
    pc.click(".sugg >> nth=2")
    check(pc.input_value("#f-step") == "KI-Anders mit Timer", "smaller: pick did not fill step input")
    pc.click("text=Übernehmen")
    check("KI-Anders mit Timer" in pc.text_content("#next-step"), "smaller: step not updated")
    # d) Kontingent aufgebraucht und Funktion fehlt
    pc.click("text=Neuer Speicherpunkt")
    S.suggest_status = 429; pc.click("text=Schritt vorschlagen"); pc.wait_for_timeout(500)
    check("aufgebraucht" in pc.text_content(".sugg-note"), "429 note missing")
    S.suggest_status = 404; pc.click("text=Andere Vorschläge"); pc.wait_for_timeout(500)
    check("noch nicht eingerichtet" in pc.text_content(".sugg-note"), "404 note missing")
    S.suggest_status = 200
    pc.screenshot(path=str(OUT / "08_pc_suggest_limit.png"), full_page=True)
    problems.extend(guest._errs)
    for d in (phone, pc, wife): problems.extend(d._errs)
    b.close()
print(json.dumps(problems, ensure_ascii=False, indent=1) if problems else "ALL OK")
