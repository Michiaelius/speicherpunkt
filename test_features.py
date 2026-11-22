"""Fokus-Timer, Kalendereintrag, Belohnung, Wochenzähler."""
import sys, json, pathlib, shutil, http.server, threading, functools, re, datetime
from playwright.sync_api import sync_playwright

OUT = pathlib.Path(sys.argv[2]); OUT.mkdir(parents=True, exist_ok=True)
SITE = OUT / "site"
if SITE.exists(): shutil.rmtree(SITE)
shutil.copytree(sys.argv[1], SITE)
class Q(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a): pass
web = http.server.ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(Q, directory=str(SITE.resolve())))
threading.Thread(target=web.serve_forever, daemon=True).start()
URL = f"http://127.0.0.1:{web.server_address[1]}/index.html"
problems = []
def check(c, m):
    if not c: problems.append(m)
def txt(pg): return pg.text_content("main")

def new_project(pg, name, step, remind=None):
    pg.click("text=+ Neues Projekt"); pg.fill("#f-name", name); pg.fill("#f-next", step)
    if remind: pg.click(f"[data-action=remind]:has-text('{remind}')")
    pg.click("button[type=submit]"); pg.wait_for_timeout(100)

with sync_playwright() as p:
    b = p.chromium.launch()
    ctx = b.new_context(viewport={"width": 390, "height": 844}, locale="de-CH", timezone_id="Europe/Zurich", accept_downloads=True)
    pg = ctx.new_page(); errs = []
    pg.on("pageerror", lambda e: errs.append(str(e)))
    pg.on("console", lambda m: errs.append(m.text) if m.type == "error" and "Failed to load resource" not in m.text else None)
    pg.clock.install(time=datetime.datetime(2026, 11, 16, 9, 0, 0))
    pg.goto(URL); pg.wait_for_timeout(300)
    pg.evaluate("localStorage.clear()"); pg.reload(); pg.wait_for_timeout(300)

    # Startseite für neue Nutzer zeigt Erklärung, für wiederkehrende nicht
    check(pg.locator(".intro .sub").count() == 1 and pg.locator("#week").count() == 0, "intro sub missing for first-time user")
    new_project(pg, "Regal, Keller; Estrich", "Schrauben, Dübel sortieren", remind="Morgen")
    check(pg.locator(".intro .sub").count() == 0, "intro explanation still shown for returning user")
    check(pg.locator("#week").count() == 0, "week line shown without anything done")

    pg.get_by_role("button", name="Weitermachen", exact=True).click()
    # 2. Kalendereintrag aus der Projektansicht
    check(pg.locator("[data-action=ics]").is_visible(), "calendar button missing in project view")
    with pg.expect_download() as dl:
        pg.click("[data-action=ics]")
    path = dl.value.path(); raw = open(path, "rb").read(); ics = raw.decode("utf-8")
    check(dl.value.suggested_filename.endswith(".ics") and "regal-keller-estrich" in dl.value.suggested_filename, "ics filename: " + dl.value.suggested_filename)
    check(ics.startswith("BEGIN:VCALENDAR\r\n") and ics.rstrip().endswith("END:VCALENDAR"), "ics envelope wrong")
    check("\n" not in ics.replace("\r\n", ""), "ics contains bare LF")
    check(all(len(l.encode()) <= 75 for l in ics.split("\r\n")), "ics line longer than 75 octets")
    unfolded = re.sub(r"\r\n[ \t]", "", ics)
    check("DTSTART:20261117T070000Z" in unfolded, "DTSTART wrong (expected tomorrow 08:00 Zurich): " + re.search(r"DTSTART:\S+", unfolded).group(0))
    check("SUMMARY:Schrauben\\, Dübel sortieren (Regal\\, Keller\\; Estrich)" in unfolded, "SUMMARY escaping wrong: " + re.search(r"SUMMARY:.*", unfolded).group(0))
    check("BEGIN:VALARM" in unfolded and "TRIGGER:PT0M" in unfolded, "alarm missing")
    check("URL:" + URL in unfolded, "app url missing")

    # 1. Fokus-Timer
    pg.click("text=Ich fange an")
    check(pg.locator(".timer-pick").is_visible(), "timer picker missing")
    pg.screenshot(path=str(OUT / "01_focus_pick.png"), full_page=True)
    pg.click(".timer-pick [data-min='10']")
    check(pg.text_content("#tr-time") == "10:00", "timer not started at 10:00: " + str(pg.text_content("#tr-time")))
    pg.clock.fast_forward("04:00"); pg.wait_for_timeout(100)
    tt = pg.text_content("#tr-time")
    check(tt in ("06:00", "05:59", "06:01"), "timer not counting down: " + str(tt))
    check("Speicherpunkt" in pg.title() and ":" in pg.title(), "title not showing countdown: " + pg.title())
    pg.screenshot(path=str(OUT / "02_focus_running.png"), full_page=True)
    pg.clock.fast_forward("06:05"); pg.wait_for_timeout(200)
    check("Zeit ist um" in pg.text_content("#timer-note"), "timer end message missing")
    check(pg.text_content("#tr-time") == "✓", "timer end mark missing")
    pg.screenshot(path=str(OUT / "03_focus_done.png"), full_page=True)
    pg.click("button:has-text('Zurück')")
    check(pg.title() == "Speicherpunkt", "title not restored after leaving finished timer: " + pg.title())
    pg.click("text=Ich fange an")
    pg.click(".timer-pick [data-min='5']"); pg.clock.fast_forward("05:05"); pg.wait_for_timeout(200)
    pg.click("text=Timer schliessen")
    check(pg.locator(".timer-pick").is_visible(), "timer close did not return to picker")
    pg.click(".timer-pick [data-min='5']"); pg.clock.fast_forward("01:00")
    pg.click("button:has-text('Zurück')")
    check(pg.title() == "Speicherpunkt", "title not restored after leaving focus: " + pg.title())

    # 3. Kalendereintrag direkt im Formular
    pg.click("text=Neuer Speicherpunkt")
    pg.click("[data-action=remind]:has-text('Nicht erinnern')")
    check(not pg.locator("[data-action=ics-draft]").is_visible(), "calendar link visible without reminder")
    pg.click("[data-action=remind]:has-text('In einer Woche')")
    check(pg.locator("[data-action=ics-draft]").is_visible(), "calendar link hidden with reminder")
    pg.fill("#f-next", "")
    pg.click("[data-action=ics-draft]")
    check(pg.locator("#err").is_visible() and "Kalendereintrag" in pg.text_content("#err"), "empty step not caught for calendar")
    pg.fill("#f-next", "Dübel kaufen")
    with pg.expect_download() as dl2:
        pg.click("[data-action=ics-draft]")
    ics2 = re.sub(r"\r\n[ \t]", "", open(dl2.value.path(), encoding="utf-8").read())
    check("DTSTART:20261123T070000Z" in ics2 and "Dübel kaufen" in ics2, "draft ics wrong")
    pg.screenshot(path=str(OUT / "04_save_calendar.png"), full_page=True)
    pg.click("text=Abbrechen")

    # 4. Belohnung und Wochenzähler
    pg.click("text=Ich fange an"); pg.click("text=Geschafft")
    check(pg.locator(".confetti").count() == 1, "confetti missing after Geschafft")
    pg.fill("#f-next", "Kisten beschriften"); pg.click("button[type=submit]"); pg.wait_for_timeout(100)
    check("1 Mini-Schritt geschafft" in (pg.text_content("#week") or ""), "week line missing after done: " + str(pg.text_content("#week") if pg.locator("#week").count() else None))
    pg.get_by_role("button", name="Weitermachen", exact=True).click()
    pg.click("text=Mehr"); pg.click("button:has-text('Abschliessen')")
    check(pg.locator(".confetti").count() >= 1, "confetti missing after finish")
    pg.click("text=Zur Übersicht")
    wk = pg.text_content("#week") or ""
    check("1 Mini-Schritt geschafft und 1 Projekt abgeschlossen" in wk, "week line after finish: " + wk)
    pg.screenshot(path=str(OUT / "05_home_week.png"), full_page=True)
    pg.clock.fast_forward(8 * 24 * 3600 * 1000); pg.reload(); pg.wait_for_timeout(300)
    check(pg.locator("#week").count() == 0, "week line still shown after 8 days")
    problems.extend(errs)

    # 5. Ohne Animationen bei reduzierter Bewegung
    ctx2 = b.new_context(reduced_motion="reduce"); pg2 = ctx2.new_page(); pg2.goto(URL); pg2.wait_for_timeout(200)
    new_project(pg2, "Ruhig", "Schritt")
    pg2.get_by_role("button", name="Weitermachen", exact=True).click(); pg2.click("text=Ich fange an"); pg2.click("text=Geschafft")
    check(pg2.locator(".confetti").count() == 0, "confetti shown despite reduced motion")
    b.close()
print(json.dumps(problems, ensure_ascii=False, indent=1) if problems else "ALL OK")
