# Speicherpunkt – Web-App

Statische Web-App, ohne Server-Code, ohne Datenbank, ohne externe Anfragen.
Alle Daten bleiben im Browser des Geräts (localStorage).

## Dateien

- `index.html` – die ganze App
- `manifest.webmanifest` – macht sie installierbar (Home-Bildschirm)
- `sw.js` – Offline-Cache
- `icons/` – App-Icons

## Veröffentlichen

Den ganzen Ordner auf einen beliebigen statischen Webhost hochladen, z. B. unter
`https://speicherpunkt.zbinden.space/`.

Wichtig: **HTTPS ist Pflicht**, sonst lassen sich Offline-Modus und Installation nicht nutzen.

## Neue Version ausrollen

1. Dateien ersetzen.
2. In `sw.js` die Zeile `const VERSION = "sp-v1";` hochzählen (`sp-v2` …),
   damit installierte Apps die neue Version laden.

## Lokal testen

    cd speicherpunkt-web
    python -m http.server 8080

Dann http://localhost:8080 öffnen.

## Abgleich zwischen Geräten (Supabase)

Projekt-URL und öffentlicher Schlüssel stehen oben in `index.html` (`SP_CONFIG`).
Einmalig in Supabase:

1. SQL Editor → Inhalt von `supabase-setup.sql` einfügen → Run.
2. Authentication → URL Configuration → Site URL: `https://speicherpunkt.zbinden.space`
3. Für die Testphase: Authentication → Sign In / Providers → Email → „Confirm email“ ausschalten.

Daten: eine Zeile pro Person in `sp_state`, geschützt durch Row Level Security.
Zusammenführen: projektweise, die jüngere Änderung gewinnt; Löschungen werden mitgeführt.
