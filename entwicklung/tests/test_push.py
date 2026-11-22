"""Erinnerungen als Mitteilung (Einstellungen, An- und Abmelden, Service Worker) und anonyme Zählung."""
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
pth = SITE / "index.html"
pth.write_text(pth.read_text(encoding="utf-8").replace("connect-src 'self' https://satqwruqmwgcflcggbul.supabase.co", "connect-src 'self' " + API), encoding="utf-8")
INIT = "window.SP_CONFIG = { url: %s, key: %s };" % (json.dumps(API), json.dumps(mock_supabase.KEY))
# Der echte Mitteilungsdienst ist im Test nicht erreichbar: Anmeldung des Geräts nachstellen (bleibt über Neuladen erhalten).
FAKE_PUSH = """(() => {
  if (!window.PushManager) return;
  const K = "__fakesub";
  const make = ep => ({ endpoint: ep, options: { applicationServerKey: null },
    toJSON() { return { endpoint: ep, keys: { p256dh: "B" + "A".repeat(86), auth: "A".repeat(22) } }; },
    unsubscribe: async () => { localStorage.removeItem(K); return true; } });
  PushManager.prototype.getSubscription = async () => { const ep = localStorage.getItem(K); return ep ? make(ep) : null; };
  PushManager.prototype.subscribe = async o => { const ep = "https://fcm.googleapis.com/fcm/send/test-" + Math.random().toString(36).slice(2);
    localStorage.setItem(K, ep); localStorage.setItem("__subkeylen", String(new Uint8Array(o.applicationServerKey).length) + ":" + o.userVisibleOnly); return make(ep); };
})();"""
# Chromium ohne Fenster meldet für Mitteilungen immer "denied". Für die Tests mit Erlaubnis wird sie nachgestellt.
FAKE_PERM = """Object.defineProperty(Notification, "permission", { get: () => "granted" }); Notification.requestPermission = async () => "granted";"""
problems = []
def check(c, m):
    if not c: problems.append(m)
def watch(pg, name):
    pg._errs = []
    pg.on("pageerror", lambda e: pg._errs.append(name + ": " + str(e)))
    pg.on("console", lambda m: pg._errs.append(name + " console: " + m.text) if m.type == "error" and "Failed to load resource" not in m.text else None)
    return pg
def settings(pg):
    if pg.locator("button.pill:has-text('Übersicht')").count(): pg.click("button.pill:has-text('Übersicht')")
    pg.click("button:has-text('Einstellungen')"); pg.wait_for_timeout(400)
def signup(pg, email):
    settings(pg); pg.click("text=Neues Konto erstellen"); pg.fill("#f-email", email); pg.fill("#f-pass", "secret1"); pg.click("#account button[type=submit]"); pg.wait_for_timeout(800)
def login(pg, email):
    settings(pg); pg.fill("#f-email", email); pg.fill("#f-pass", "secret1"); pg.click("#account button[type=submit]"); pg.wait_for_timeout(900)
def new_project(pg, name, step, remind=None):
    pg.click("text=+ Neues Projekt"); pg.fill("#f-name", name); pg.fill("#f-next", step)
    if remind: pg.click(f"[data-action=remind][data-k='{remind}']")
    pg.click("form[data-form=save] button[type=submit]"); pg.wait_for_timeout(300)

with sync_playwright() as p:
    b = p.chromium.launch()

    # 1. Ohne Erlaubnis für Mitteilungen
    ctx = b.new_context(viewport={"width": 390, "height": 844}, locale="de-CH"); ctx.add_init_script(INIT); ctx.add_init_script(FAKE_PUSH)
    pg = watch(ctx.new_page(), "ohne"); pg.goto(BASE); pg.wait_for_timeout(1200)
    check(len(S.visits) == 1, f"Zählung: genau ein Eintrag beim ersten Öffnen: {S.visits}")
    dev = pg.evaluate("localStorage.getItem('speicherpunkt.device')")
    check(dev and S.visits and S.visits[0][0] == dev and len(dev) == 36, "Zählung: Gerätenummer stimmt nicht")
    pg.reload(); pg.wait_for_timeout(800); pg.evaluate("document.dispatchEvent(new Event('visibilitychange'))"); pg.wait_for_timeout(300)
    check(len(S.visits) == 1, f"Zählung: am selben Tag kein zweiter Eintrag: {len(S.visits)}")
    settings(pg)
    check("Melde dich oben an" in pg.text_content("#push-status"), "ohne Konto: Hinweis aufs Anmelden: " + pg.text_content("#push"))
    check("zählt die App anonym" in pg.text_content("#count-info"), "Hinweis zur Zählung fehlt")
    pg.click("[data-action=count-toggle]")
    check(pg.evaluate("localStorage.getItem('speicherpunkt.nocount')") == "1" and pg.evaluate("localStorage.getItem('speicherpunkt.device')") is None and "ausgeschaltet" in pg.text_content("#count-info"), "Zählung ausschalten")
    pg.evaluate("localStorage.removeItem('speicherpunkt.seen')"); pg.reload(); pg.wait_for_timeout(800)
    check(len(S.visits) == 1, "Zählung läuft trotz Ausschalten")
    signup(pg, "nein@example.ch"); settings(pg)
    if pg.locator("[data-action=push-on]").count():
        pg.click("[data-action=push-on]"); pg.wait_for_timeout(500)
        check("nicht erlaubt" in pg.text_content("#push") or "blockiert" in pg.text_content("#push"), "abgelehnte Erlaubnis: Meldung fehlt: " + pg.text_content("#push"))
    else:
        check("blockiert" in pg.text_content("#push-status"), "blockiert: Hinweis fehlt: " + pg.text_content("#push"))
    check(not S.push_subs, "Gerät angemeldet ohne Erlaubnis")
    problems.extend(pg._errs); ctx.close()

    # 2. Mit Erlaubnis: einschalten, abmelden, anmelden, ausschalten
    ctx = b.new_context(viewport={"width": 390, "height": 844}, locale="de-CH", permissions=["notifications"]); ctx.add_init_script(INIT); ctx.add_init_script(FAKE_PUSH); ctx.add_init_script(FAKE_PERM)
    pg = watch(ctx.new_page(), "mit"); pg.goto(BASE); pg.wait_for_timeout(1200)
    signup(pg, "ja@example.ch"); uid = S.users["ja@example.ch"]["id"]
    new_project(pg, "Steuern", "Lohnausweis suchen", remind="1"); pg.wait_for_timeout(300)
    check(pg.locator("#push-hint").is_visible(), "Tipp auf der Startseite fehlt (Projekt mit Erinnerung, Mitteilungen aus)")
    pg.click("#push-hint button"); pg.wait_for_timeout(400)
    check(pg.locator("[data-action=push-on]").is_visible(), "Knopf zum Einschalten fehlt: " + pg.text_content("#push"))
    pg.screenshot(path=str(OUT / "push_aus.png"), full_page=True)
    S.push_key = None; pg.click("[data-action=push-on]"); pg.wait_for_timeout(500)
    check("noch nicht eingerichtet" in pg.text_content("#push-err") and not S.push_subs, "Server ohne Schlüssel: " + pg.text_content("#push"))
    S.push_key = mock_supabase.Store().push_key; S.push_missing = True; pg.click("[data-action=push-on]"); pg.wait_for_timeout(500)
    check("noch nicht eingerichtet" in pg.text_content("#push-err") and not S.push_subs, "SQL fehlt: " + pg.text_content("#push"))
    S.push_missing = False; pg.click("[data-action=push-on]"); pg.wait_for_timeout(600)
    ep = next(iter(S.push_subs), None)
    check(ep and S.push_subs[ep]["uid"] == uid and len(S.push_subs[ep]["p256dh"]) == 87, f"Gerät nicht angemeldet: {S.push_subs}")
    check(pg.evaluate("localStorage.getItem('__subkeylen')") == "65:true", "Schlüssel für den Browser falsch: " + str(pg.evaluate("localStorage.getItem('__subkeylen')")))
    check("eingeschaltet" in pg.text_content("#push-status") and pg.locator("#push-err").count() == 0, "Status nach Einschalten: " + pg.text_content("#push"))
    pg.screenshot(path=str(OUT / "push_ein.png"), full_page=True)
    pg.click("[data-action=push-test]"); pg.wait_for_timeout(500)
    check("unterwegs" in pg.text_content("#toast") and S.push_tests == [ep], f"Probe-Mitteilung: {pg.text_content('#toast')} {S.push_tests}")
    check(pg.locator("[data-action=push-test]").is_disabled(), "Probe-Knopf sollte kurz gesperrt sein")
    pg.click("button.pill:has-text('Übersicht')"); check(pg.locator("#push-hint").count() == 0, "Tipp noch da, obwohl eingeschaltet")
    pg.reload(); pg.wait_for_timeout(1200); check(pg.locator("#push-hint").count() == 0 and ep in S.push_subs, "nach Neuladen")
    # abmelden: Gerät wird beim Konto entfernt; neu anmelden: kommt von selbst wieder
    settings(pg); pg.click("[data-action=logout]"); pg.click("[data-action=logout-yes]"); pg.wait_for_timeout(900)
    check(not S.push_subs, f"nach Abmelden noch angemeldet: {S.push_subs}")
    check("Melde dich oben an" in pg.text_content("#push-status"), "nach Abmelden: " + pg.text_content("#push"))
    S.users["andere@example.ch"] = {"id": "00000000-0000-4000-8000-000000000002", "password": "secret1"}
    login(pg, "andere@example.ch"); pg.wait_for_timeout(500)
    check(ep in S.push_subs and S.push_subs[ep]["uid"] == "00000000-0000-4000-8000-000000000002", f"anderes Konto am selben Gerät übernimmt die Anmeldung: {S.push_subs}")
    settings(pg); check("eingeschaltet" in pg.text_content("#push-status"), "Status nach erneutem Anmelden: " + pg.text_content("#push"))
    pg.click("[data-action=push-off]"); pg.wait_for_timeout(500)
    check(not S.push_subs and pg.evaluate("localStorage.getItem('speicherpunkt.push')") is None and pg.evaluate("localStorage.getItem('__fakesub')") is None, "Ausschalten")
    check(pg.locator("[data-action=push-on]").is_visible(), "nach Ausschalten wieder Knopf zum Einschalten")
    # Konto löschen meldet das Gerät ab
    pg.click("[data-action=push-on]"); pg.wait_for_timeout(500); check(len(S.push_subs) == 1, "wieder einschalten")
    pg.click("[data-action=delete-account]"); pg.fill("#f-delete", "löschen"); pg.click("[data-action=delete-account-yes]"); pg.wait_for_timeout(800)
    check(not S.push_subs and pg.evaluate("localStorage.getItem('__fakesub')") is None and pg.evaluate("localStorage.getItem('speicherpunkt.push')") is None, "Konto löschen meldet das Gerät nicht ab")
    problems.extend(pg._errs); ctx.close()

    # 3. Aus einer Mitteilung geöffnet: ?p=<Projekt>
    ctx = b.new_context(viewport={"width": 390, "height": 844}, locale="de-CH"); ctx.add_init_script(INIT)
    pg = watch(ctx.new_page(), "link"); pg.goto(BASE); pg.wait_for_timeout(600)
    new_project(pg, "Erstes", "Schritt eins"); new_project(pg, "Zweites", "Schritt zwei")
    pid = pg.evaluate("JSON.parse(localStorage.getItem('speicherpunkt.v1')).projects[0].id")
    pg.goto(BASE + "?p=" + pid); pg.wait_for_timeout(600)
    check("Schritt eins" in pg.text_content("main") and "Schritt zwei" not in pg.text_content("main") and "?p=" not in pg.url, "?p= öffnet nicht das Projekt: " + pg.url)
    pg.goto(BASE + "?p=gibtsnicht"); pg.wait_for_timeout(500)
    check("+ Neues Projekt" in pg.text_content("main") and "?p=" not in pg.url, "unbekanntes Projekt in ?p= sollte zur Übersicht führen")
    pg.goto(BASE); pg.wait_for_timeout(1000)
    pg.evaluate("id => navigator.serviceWorker.dispatchEvent(new MessageEvent('message', { data: { open: id } }))", pid); pg.wait_for_timeout(500)
    check("Schritt eins" in pg.text_content("main") and "Schritt zwei" not in pg.text_content("main"), "Nachricht vom Service Worker öffnet das Projekt nicht")
    problems.extend(pg._errs); ctx.close()

    # 4. iPhone im Browser (ohne Installation): Hinweis statt Knopf
    ctx = b.new_context(viewport={"width": 390, "height": 844}, locale="de-CH", user_agent="Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Mobile/15E148 Safari/604.1")
    ctx.add_init_script(INIT); ctx.add_init_script("delete window.PushManager;")
    pg = watch(ctx.new_page(), "ios"); pg.goto(BASE); pg.wait_for_timeout(600); settings(pg)
    check("Home-Bildschirm" in pg.text_content("#push-status") and pg.locator("[data-action=push-on]").count() == 0, "iPhone-Hinweis fehlt: " + pg.text_content("#push"))
    problems.extend(pg._errs); ctx.close()

    # 5. Service Worker: zeigt die Mitteilung an und reagiert auf den Tipp (Ereignisse direkt im Worker ausgelöst)
    ctx = b.new_context(viewport={"width": 390, "height": 844}, locale="de-CH", permissions=["notifications"]); ctx.add_init_script(INIT)
    pg = watch(ctx.new_page(), "sw"); pg.goto(BASE); pg.wait_for_timeout(1500)
    sw = ctx.service_workers[0] if ctx.service_workers else None
    check(sw is not None, "Service Worker läuft nicht")
    if sw:
        res = sw.evaluate("""async () => {
          const shown = []; const orig = self.registration.showNotification.bind(self.registration);
          self.registration.showNotification = (t, o) => { shown.push({ t, o }); return Promise.resolve(); };
          const fire = data => new Promise(res => { const e = new Event("push"); e.data = data; e.waitUntil = p => Promise.resolve(p).then(res, res); self.dispatchEvent(e); });
          await fire({ json: () => ({ t: "Steuern", b: "Nächster Schritt: Lohnausweis suchen", p: "abc123" }) });
          await fire({ json: () => { throw new Error("kaputt"); } });
          await fire(null);
          self.registration.showNotification = orig;
          const opened = [], msgs = []; let focused = 0;
          const realClients = self.clients;
          const run = (list, p) => new Promise(res => {
            const fake = { matchAll: async () => list, openWindow: async u => { opened.push(u); } };
            Object.defineProperty(self, "clients", { value: fake, configurable: true });
            const e = new Event("notificationclick"); e.notification = { close() {}, data: { p } }; e.waitUntil = pr => Promise.resolve(pr).then(res, res); self.dispatchEvent(e);
          });
          await run([], "abc123");
          await run([{ url: self.registration.scope + "index.html", focus: async () => { focused++; }, postMessage: m => msgs.push(m) }], "abc123");
          await run([], "");
          Object.defineProperty(self, "clients", { value: realClients, configurable: true });
          return { shown, opened, msgs, focused, scope: self.registration.scope };
        }""")
        s0 = res["shown"]
        check(len(s0) == 3 and s0[0]["t"] == "Steuern" and s0[0]["o"]["body"] == "Nächster Schritt: Lohnausweis suchen" and s0[0]["o"]["tag"] == "sp-abc123" and s0[0]["o"]["data"]["p"] == "abc123", f"Mitteilung im Worker: {s0}")
        check(len(s0) == 3 and s0[1]["t"] == "Speicherpunkt" and s0[2]["o"]["body"] == "Dein nächster Schritt wartet.", f"kaputte oder leere Daten: neutrale Mitteilung: {s0}")
        check(res["opened"] == [res["scope"] + "?p=abc123", res["scope"]], f"Tipp öffnet die App beim Projekt: {res['opened']}")
        check(res["focused"] == 1 and res["msgs"] == [{"open": "abc123"}], f"offene App wird nach vorne geholt: {res['focused']} {res['msgs']}")
    problems.extend(pg._errs); ctx.close()
    b.close()
print(json.dumps(problems, ensure_ascii=False, indent=1) if problems else "ALL OK")
