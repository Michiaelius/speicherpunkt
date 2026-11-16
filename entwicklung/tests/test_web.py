import sys, json, time, pathlib, re
from playwright.sync_api import sync_playwright

import shutil
OUT = pathlib.Path(sys.argv[2]); OUT.mkdir(parents=True, exist_ok=True)
SITE = OUT / "site"
if SITE.exists(): shutil.rmtree(SITE)
shutil.copytree(sys.argv[1], SITE)
import http.server, threading, functools, socket
_sock=socket.socket(); _sock.bind(("127.0.0.1",0)); PORT=_sock.getsockname()[1]; _sock.close()
_h=functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(SITE.resolve()))
class Q(_h.func):
    def log_message(self,*a): pass
_srv=http.server.ThreadingHTTPServer(("127.0.0.1",PORT), functools.partial(Q, directory=str(SITE.resolve())))
threading.Thread(target=_srv.serve_forever, daemon=True).start()
URL = f"http://127.0.0.1:{PORT}/index.html"

MOCK = """
window.__store = window.__store || {};
(function(){
  const store = JSON.parse(localStorage.getItem('mockdb')||'{}');
  function save(){ localStorage.setItem('mockdb', JSON.stringify(store)); }
  const listeners = {};
  window.__mockWrites = 0;
  const db = { doc(path){ return {
      path,
      async get(){ return { exists: path in store, data: ()=> store[path] ? JSON.parse(JSON.stringify(store[path])) : undefined, metadata:{fromCache:false,hasPendingWrites:false} }; },
      async set(d){ window.__mockWrites++; store[path]=JSON.parse(JSON.stringify(d)); save(); },
      onSnapshot(next){ (listeners[path]=listeners[path]||[]).push(next); return ()=>{}; }
  }; } };
  const user = { async id(){ return 'u_test123'; } };
  window.claude = { use: async (n)=> n==='db'? db : n==='user'? user : null };
})();
"""

problems = []
TZ = sys.argv[3] if len(sys.argv) > 3 else 'Europe/Zurich'
def check(cond, msg):
    if not cond: problems.append(msg)

def run(mobile=False, dark=False, cloud=False, tag=""):
    with sync_playwright() as p:
        b = p.chromium.launch()
        ctx = b.new_context(timezone_id=TZ, locale="de-CH", viewport={"width": 390, "height": 844} if mobile else {"width": 1200, "height": 900},
                            color_scheme="dark" if dark else "light", permissions=["clipboard-read", "clipboard-write"])
        if cloud: ctx.add_init_script(MOCK)
        ctx.route(re.compile(r'https://fonts\.(googleapis|gstatic)\.com/.*'), lambda r: r.fulfill(status=200, body='', content_type='text/css'))
        pg = ctx.new_page()
        global LASTPG; LASTPG = pg
        errs = []
        pg.on("pageerror", lambda e: errs.append(str(e)))
        pg.on("console", lambda m: errs.append(m.text) if m.type == "error" else None)
        pg.goto(URL); pg.wait_for_timeout(300)
        pg.evaluate("localStorage.clear()"); pg.reload(); pg.wait_for_timeout(300)
        t = tag
        # 1 examples
        check(pg.locator("#examples-note").is_visible(), t+"examples banner missing")
        check("Gartenhaus" in pg.text_content("main"), t+"example project missing")
        check("Sanfte Erinnerung" in pg.text_content("main"), t+"due reminder card missing")
        pg.screenshot(path=str(OUT / f"{t}01_home.png"), full_page=True)
        # example: open + start + done flow
        pg.get_by_role("button", name="Weitermachen", exact=True).click(); pg.wait_for_timeout(100)
        check("Hier warst du stehen geblieben" in pg.text_content("main"), t+"return view missing")
        check(pg.locator("#welcome").count()==1, t+"welcome-back line missing for 12-day-old save")
        pg.screenshot(path=str(OUT / f"{t}02_return.png"), full_page=True)
        pg.click("text=Ich fange an")
        check("Nur das hier" in pg.text_content("main"), t+"focus view missing")
        pg.screenshot(path=str(OUT / f"{t}03_focus.png"), full_page=True)
        pg.click("text=Geschafft")
        check("Was kommt als Nächstes" in pg.text_content("main"), t+"after-done heading missing")
        pg.fill("#f-next", "Zweite Wand grundieren"); pg.click("button[type=submit]")
        check(pg.locator("#examples-note").is_visible(), t+"examples should remain until real project")
        # 2 new project with validation
        pg.click("text=Neues Projekt")
        pg.screenshot(path=str(OUT / f"{t}04_new.png"), full_page=True)
        pg.click("button[type=submit]")
        check(pg.locator("#name-err").is_visible(), t+"name validation missing")
        pg.fill("#f-name", "<img src=x onerror=window.__xss=1>App bauen")
        pg.click("button[type=submit]")
        check(pg.locator("#err").is_visible(), t+"next validation missing")
        check(pg.input_value("#f-name").startswith("<img"), t+"name lost after validation")
        pg.fill("#f-where", "Konzept steht, Analyse ist fertig.")
        pg.fill("#f-next", "Ordner für das Projekt anlegen")
        pg.click("text=In einer Woche")
        pg.click("button[type=submit]"); pg.wait_for_timeout(100)
        check(pg.evaluate("window.__xss") is None, t+"XSS executed")
        check(pg.locator("#examples-note").count() == 0, t+"examples still shown after real project")
        check("Ordner für das Projekt anlegen" in pg.text_content("main"), t+"new project not suggested")
        pg.screenshot(path=str(OUT / f"{t}05_home_real.png"), full_page=True)
        # persistence
        pg.wait_for_timeout(900)
        pg.reload(); pg.wait_for_timeout(400)
        check("Ordner für das Projekt anlegen" in pg.text_content("main"), t+"not persisted after reload")
        # 3 edit step, start, done
        pg.get_by_role("button", name="Weitermachen", exact=True).click()
        check("Erinnerung" in pg.text_content("main"), t+"reminder label missing in project view")
        pg.click("text=Schritt kleiner machen")
        pg.fill("#f-step", "Nur den Datei-Explorer öffnen"); pg.click("text=Übernehmen")
        check("Nur den Datei-Explorer öffnen" in pg.inner_text("#next-step"), t+"edit step failed")
        pg.click("text=Ich fange an"); pg.click("text=Geschafft")
        pg.fill("#f-where", "Ordner existiert."); pg.fill("#f-next", "README anlegen"); pg.click("button[type=submit]")
        pg.get_by_role("button", name="Weitermachen", exact=True).click()
        check("Speicherpunkt 2" in pg.text_content("main"), t+"save count wrong")
        pg.click("text=Frühere Speicherpunkte (1)")
        check("erledigt" in pg.text_content("main"), t+"done flag missing in history")
        pg.screenshot(path=str(OUT / f"{t}06_project_hist.png"), full_page=True)
        # interrupt save
        pg.click("text=Ich fange an"); pg.click("text=Unterbrechen und speichern")
        check(pg.input_value("#f-next") == "README anlegen", t+"interrupt prefill missing")
        check("Speicherpunkt setzen" in pg.text_content("main"), t+"interrupt save view missing")
        pg.click("text=← Abbrechen")
        check("Hier warst du" in pg.text_content("main"), t+"cancel from save should go back to project")
        # 4 pause / resume
        pg.click("text=Mehr"); pg.click("text=Ruhen lassen")
        check("ruht" in pg.text_content("main"), t+"pause failed")
        check(pg.locator("text=Aufwecken").count() >= 1, t+"resume button missing")
        pg.click("text=← Übersicht")
        check("Alles ruht gerade" in pg.text_content("main"), t+"all-resting state missing")
        check("Ruhen gerade (1)" in pg.text_content("main"), t+"resting group missing")
        pg.screenshot(path=str(OUT / f"{t}07_resting.png"), full_page=True)
        pg.click(".proj"); pg.click("button:has-text('Aufwecken')")
        check("ruht" not in pg.inner_text("header .eyebrow"), t+"resume failed")
        # 5 rename + second project + delete
        pg.click("text=Mehr"); pg.click("text=Umbenennen"); pg.fill("#f-rename", "Speicherpunkt-App"); pg.click("button[type=submit]")
        check("Speicherpunkt-App" in pg.text_content("main"), t+"rename failed")
        pg.click("text=← Übersicht")
        pg.click("text=Neues Projekt"); pg.fill("#f-name", "Steuern"); pg.fill("#f-next", "Lohnausweis suchen"); pg.click("button[type=submit]")
        check("Weitere Projekte" in pg.text_content("main"), t+"other projects list missing")
        pg.click(".proj:has-text('Speicherpunkt-App')") if pg.locator(".proj:has-text('Speicherpunkt-App')").count() else pg.get_by_role("button", name="Weitermachen", exact=True).click()
        name_now = pg.inner_text("header .eyebrow")
        pg.click("text=Mehr"); pg.click("button:has-text('Löschen')")
        check("Wirklich" in pg.text_content("main") or "löschen?" in pg.text_content("main"), t+"delete confirm missing")
        pg.click("text=Ja, löschen")
        check(pg.locator(".proj").count() == 0, t+"delete failed or list wrong")
        # 6 reminder due + snooze
        pg.evaluate("""()=>{const s=JSON.parse(localStorage.getItem('speicherpunkt.v1'));s.projects[0].remindAt=Date.now()-1000;s.updated=Date.now()+5000;localStorage.setItem('speicherpunkt.v1',JSON.stringify(s));}""")
        if cloud:
            pg.evaluate("""()=>{const m=JSON.parse(localStorage.getItem('mockdb')||'{}');for(const k in m){m[k]=JSON.parse(localStorage.getItem('speicherpunkt.v1'));}localStorage.setItem('mockdb',JSON.stringify(m));}""")
        pg.reload(); pg.wait_for_timeout(500)
        check("Sanfte Erinnerung" in pg.text_content("main"), t+"due reminder not shown")
        pg.click("text=Morgen wieder")
        check("Sanfte Erinnerung" not in pg.text_content("main"), t+"snooze failed")
        # 7 settings export/import
        pg.click("text=Einstellungen")
        info = pg.inner_text("#storage-info")
        check("diesem Gerät" in info and "vorübergehend" not in info, t+"storage info wrong: "+info)
        pg.click("text=Sicherung kopieren"); pg.wait_for_timeout(200)
        clip = pg.evaluate("navigator.clipboard.readText()")
        check('"projects"' in clip, t+"export clipboard failed")
        pg.fill("#f-import", "kaputt"); pg.click("text=Einfügen und ersetzen")
        check(pg.locator("#imp-err").is_visible(), t+"import error missing")
        pg.fill("#f-import", clip); pg.click("text=Einfügen und ersetzen")
        check(pg.locator("#imp-confirm").is_visible(), t+"import confirm missing")
        pg.click("text=Ja, ersetzen")
        check("Steuern" in pg.text_content("main"), t+"import failed")
        pg.screenshot(path=str(OUT / f"{t}08_after_import.png"), full_page=True)
        pg.click("text=Einstellungen"); pg.screenshot(path=str(OUT / f"{t}09_settings.png"), full_page=True)
        pg.click("text=Alle Projekte löschen"); pg.click("text=Ja, alles löschen")
        check(pg.locator("#examples-note").is_visible(), t+"wipe should show examples again")
        # layout
        ov = pg.evaluate("document.documentElement.scrollWidth > window.innerWidth + 1")
        check(not ov, t+"horizontal overflow")
        if cloud:
            pg.wait_for_timeout(1000)
            check(pg.evaluate("window.__mockWrites") > 0, t+"no cloud writes")
            stored = pg.evaluate("JSON.parse(localStorage.getItem('mockdb')||'{}')")
            check("data/users/u_test123/speicherpunkt" in stored, t+"cloud doc path wrong: "+str(list(stored)))
        # cloud load on fresh browser: localStorage cleared, data comes from mock
        if cloud:
            pg.click("text=Neues Projekt"); pg.fill("#f-name", "Wolke"); pg.fill("#f-next", "Test"); pg.click("button[type=submit]")
            pg.wait_for_timeout(1200)
            pg.evaluate("localStorage.removeItem('speicherpunkt.v1')"); pg.reload(); pg.wait_for_timeout(600)
            check("Wolke" in pg.text_content("main"), t+"cloud data not loaded on fresh browser")
        for e in errs: problems.append(t+"console: "+e)
        b.close()

import traceback
for kw in [dict(tag="desk_"), dict(mobile=True, dark=True, tag="mob_dark_"), dict(mobile=True, tag="mob_light_")]:
    try: run(**kw)
    except Exception as e: problems.append(kw["tag"]+"CRASH: "+str(e).splitlines()[0])

def run_edge(tag="edge_"):
    t=tag
    with sync_playwright() as p:
        b = p.chromium.launch(); ctx=b.new_context(viewport={"width":320,"height":640}); ctx.route(re.compile(r'https://fonts\.(googleapis|gstatic)\.com/.*'), lambda r: r.fulfill(status=200, body='', content_type='text/css')); pg=ctx.new_page()
        errs=[]; pg.on("pageerror", lambda e: errs.append(str(e)))
        pg.goto(URL); pg.evaluate("localStorage.clear()"); pg.reload(); pg.wait_for_timeout(200)
        longw = "Donaudampfschifffahrtsgesellschaftskapitänsmützenhalterung"*3
        pg.click("text=Neues Projekt"); pg.fill("#f-name", longw[:80]); pg.fill("#f-where", longw*5); pg.fill("#f-next", longw[:200]); pg.click("button[type=submit]")
        check(not pg.evaluate("document.documentElement.scrollWidth > window.innerWidth + 1"), t+"overflow home long text")
        pg.get_by_role("button", name="Weitermachen", exact=True).click()
        check(not pg.evaluate("document.documentElement.scrollWidth > window.innerWidth + 1"), t+"overflow project long text")
        pg.screenshot(path=str(OUT/f"{t}long.png"), full_page=True)
        # keyboard: tab to first button and activate
        pg.click("text=← Übersicht"); pg.keyboard.press("Tab"); pg.keyboard.press("Tab")
        foc = pg.evaluate("document.activeElement && document.activeElement.tagName")
        check(foc=="BUTTON", t+"keyboard focus not on button: "+str(foc))
        # Enter submits new project form
        pg.click("text=Neues Projekt"); pg.fill("#f-name","Tastatur"); pg.fill("#f-next","Schritt"); pg.press("#f-next","Enter")
        check("Tastatur" in pg.text_content("main") or "Schritt" in pg.text_content("main"), t+"enter submit failed")
        # storage blocked: simulate throwing localStorage
        ctx2=b.new_context(); ctx2.add_init_script("Object.defineProperty(window,'localStorage',{get(){throw new Error('blocked')}})")
        pg2=ctx2.new_page(); pg2.on("pageerror", lambda e: errs.append("blocked: "+str(e)))
        pg2.goto(URL); pg2.wait_for_timeout(200)
        check("Gartenhaus" in pg2.text_content("main"), t+"render fails with blocked storage")
        pg2.click("text=Neues Projekt"); pg2.fill("#f-name","X"); pg2.fill("#f-next","Y"); pg2.click("button[type=submit]")
        pg2.click("text=Einstellungen"); check("vorübergehend" in pg2.inner_text("#storage-info"), t+"blocked storage info wrong")
        for e in errs: problems.append(t+"console: "+e)
        b.close()
def run_pwa():
    with sync_playwright() as p:
        b=p.chromium.launch(); ctx=b.new_context(); pg=ctx.new_page(); errs=[]
        pg.on("pageerror", lambda e: errs.append(str(e)))
        pg.on("console", lambda m: errs.append(m.text) if m.type=="error" else None)
        pg.goto(URL); pg.wait_for_timeout(1500)
        reg = pg.evaluate("navigator.serviceWorker.getRegistration().then(r=>!!(r&&(r.active||r.installing||r.waiting)))")
        check(reg, "pwa: service worker not registered")
        man = pg.evaluate("fetch('manifest.webmanifest').then(r=>r.json())")
        check(man.get("display")=="standalone" and len(man.get("icons",[]))>=2, "pwa: manifest wrong")
        for ic in man["icons"]:
            st = pg.evaluate(f"fetch('{ic['src']}').then(r=>r.status)"); check(st==200, "pwa: icon missing "+ic["src"])
        pg.reload(); pg.wait_for_timeout(800)
        ctx.set_offline(True); pg.reload(); pg.wait_for_timeout(500)
        check("Speicherpunkt" in pg.text_content("body"), "pwa: offline load failed")
        ext = pg.evaluate("performance.getEntriesByType('resource').map(e=>e.name).filter(n=>!n.startsWith(location.origin))")
        check(not ext, "pwa: external requests "+str(ext))
        for e in errs:
            if "ERR_INTERNET_DISCONNECTED" not in e: problems.append("pwa console: "+e)
        b.close()

def run_finish(tag="fin_"):
    t=tag
    with sync_playwright() as p:
        b=p.chromium.launch(); ctx=b.new_context(viewport={"width":390,"height":844}); pg=ctx.new_page(); errs=[]
        pg.on("pageerror", lambda e: errs.append(str(e)))
        pg.goto(URL); pg.evaluate("localStorage.clear()"); pg.reload(); pg.wait_for_timeout(300)
        # A: finish after done, with final note
        pg.click("text=+ Neues Projekt"); pg.fill("#f-name","Regal bauen"); pg.fill("#f-next","Letzte Schraube"); pg.click("button[type=submit]")
        pg.get_by_role("button", name="Weitermachen", exact=True).click()
        pg.click("text=Ich fange an"); pg.click("text=Geschafft")
        check(pg.locator(".finish-offer").is_visible(), t+"finish offer missing after done")
        pg.screenshot(path=str(OUT/f"{t}01_offer.png"), full_page=True)
        pg.fill("#f-where","Regal steht im Wohnzimmer.")
        pg.click("text=Projekt abschliessen"); pg.wait_for_timeout(100)
        txt=pg.text_content("main")
        check("Abgeschlossen" in txt and "Regal bauen" in txt, t+"finished view missing")
        check("2 Speicherpunkte" in txt, t+"final note not saved: "+pg.text_content("#fin-stats"))
        check("Regal steht im Wohnzimmer" in txt, t+"final where not shown")
        pg.screenshot(path=str(OUT/f"{t}02_finished.png"), full_page=True)
        pg.click("text=Zur Übersicht")
        txt=pg.text_content("main")
        check("Alles abgeschlossen" in txt, t+"all-finished hero missing")
        check("Abgeschlossen (1)" in txt, t+"finished group missing")
        check("Sanfte Erinnerung" not in txt and "Hier könntest du weitermachen" not in txt, t+"finished project still suggested")
        # persist
        pg.wait_for_timeout(300); pg.reload(); pg.wait_for_timeout(300)
        check("Abgeschlossen (1)" in pg.text_content("main"), t+"finished not persisted")
        pg.screenshot(path=str(OUT/f"{t}03_home.png"), full_page=True)
        # B: reopen then cancel keeps finished
        pg.click("summary:has-text('Abgeschlossen')"); pg.click(".proj.finished")
        pg.click("text=Wieder öffnen")
        check("Wieder öffnen: Wie geht es weiter?" in pg.text_content("main"), t+"reopen view missing")
        pg.click("text=← Abbrechen")
        check("Abgeschlossen ·" in pg.text_content("main"), t+"cancel reopen should stay finished")
        # C: reopen and save
        pg.click("text=Wieder öffnen"); pg.fill("#f-next","Zweites Regal planen"); pg.click("button[type=submit]")
        txt=pg.text_content("main")
        check("Zweites Regal planen" in txt and "Abgeschlossen (" not in txt, t+"reopen+save failed")
        # D: finish via menu without done
        pg.get_by_role("button", name="Weitermachen", exact=True).click()
        pg.click("text=Mehr"); pg.click("button:has-text('Abschliessen')")
        check("Abgeschlossen ·" in pg.text_content("main"), t+"menu finish failed")
        # E: finished project has no reminder even if remindAt was set
        pg.click("text=Zur Übersicht")
        check("Erinnerung" not in pg.text_content("main").replace("Sanfte Erinnerung",""), t+"finished shows reminder")
        # F: example finish works in memory
        pg.evaluate("localStorage.clear()"); pg.reload(); pg.wait_for_timeout(200)
        pg.click(".proj:has-text('Bewerbungsunterlagen')"); pg.click("text=Mehr"); pg.click("button:has-text('Abschliessen')")
        check("Abgeschlossen ·" in pg.text_content("main"), t+"example finish failed")
        check(not pg.evaluate("document.documentElement.scrollWidth > window.innerWidth + 1"), t+"overflow")
        for e in errs: problems.append(t+"console: "+e)
        b.close()
try: run_finish()
except Exception as e: problems.append('finish CRASH: '+str(e).splitlines()[0])
try: run_pwa()
except Exception as e: problems.append('pwa CRASH: '+str(e).splitlines()[0])
try: run_edge()
except Exception as e: problems.append('edge CRASH: '+str(e).splitlines()[0])
print(json.dumps(problems, ensure_ascii=False, indent=1) if problems else "ALL OK")
