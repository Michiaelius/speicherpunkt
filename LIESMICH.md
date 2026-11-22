# Speicherpunkt

Web-App für Menschen, die beim Dranbleiben Mühe haben: Vor dem Aufhören einen Speicherpunkt setzen,
beim Zurückkommen sehen, wo man war, und genau einen nächsten Mini-Schritt.

Statische Seite (GitHub Pages) plus Supabase für Konten, Abgleich und KI-Vorschläge.

## Dateien

| Datei / Ordner | Zweck |
| --- | --- |
| `index.html` | die ganze App (Aussehen, Logik, Texte) |
| `willkommen/` | Landingpage mit Warteliste (speicherpunkt.zbinden.space/willkommen/) |
| `datenschutz.html`, `impressum.html` | Rechtstexte; gelb markierte Stellen vor dem Veröffentlichen ausfüllen |
| `seiten.css` | gemeinsames Aussehen von Landingpage und Rechtstexten |
| `sw.js` | Offline-Cache, damit die App ohne Internet startet |
| `manifest.webmanifest`, `icons/` | macht die App installierbar |
| `fonts/` | Lora und Inter, mitgeliefert (keine Anfragen an Google) |
| `supabase-setup.sql` | Tabellen und Regeln in Supabase |
| `supabase/functions/suggest-step/index.ts` | Edge Function für KI-Vorschläge |
| `supabase/functions/api/index.ts` | Edge Function für die Schnittstelle (ZbiWeb und andere Programme) |
| `SCHNITTSTELLE.md` | Vertrag der Schnittstelle, Version 2 (für ZbiWeb) |
| `entwicklung/tests/` | automatische Tests (werden nicht von der App geladen) |
| `ÄNDERUNGEN.md` | was sich in welcher Version geändert hat |

## Neue Version ausrollen

1. Alle Dateien im GitHub-Repository ersetzen.
2. In `sw.js` steht `const VERSION = "sp-v8";`. Bei jeder neuen Version hochzählen,
   damit installierte Apps die neuen Dateien laden.
3. Die Version steht auch in `index.html` (`APP_VERSION`) und unten in den Einstellungen der App.
   So siehst du auf dem Handy, ob die neue Version angekommen ist.

## Supabase einrichten (einmalig)

1. **SQL Editor:** Inhalt von `supabase-setup.sql` einfügen und ausführen. Darf mehrmals ausgeführt werden.
2. **Authentication → URL Configuration:** Site URL `https://speicherpunkt.zbinden.space`
3. **Authentication → Sign In / Providers → Email:** „Confirm email“ aus (Testphase).
4. **E-Mails für „Passwort vergessen“:** Supabase verschickt ohne eigenen Mailserver nur E-Mails an Mitglieder
   des eigenen Supabase-Teams, höchstens etwa 2 pro Stunde. Für alle anderen unter
   Authentication → Emails → SMTP einen eigenen Absender eintragen (z. B. ein Postfach bei Infomaniak oder Resend).

Projekt-URL und öffentlicher Schlüssel stehen in `index.html` bei `SP_CONFIG` und in `willkommen/warteliste.js`.
Die Supabase-Adresse steht zusätzlich in der `Content-Security-Policy` oben in `index.html` und `willkommen/index.html`.
Ändert sie sich, an allen vier Stellen anpassen.

**Warteliste anschauen:** Supabase → Table Editor → Tabelle `sp_waitlist` (E-Mail, Antwort auf die Frage, Quelle, Datum).
Die Quelle kommt aus dem Link: `…/willkommen/?q=instagram` speichert „instagram“. So siehst du, welcher Kanal Leute bringt.

**Konto löschen:** läuft über die Datenbankfunktion `sp_delete_account` und löscht Konto, Projekte und Kontingent.

Daten: eine Zeile pro Person in `sp_state`, geschützt durch Row Level Security.
Abgleich: projektweise, die jüngere Änderung gewinnt; Löschungen werden mitgeführt.

## KI-Vorschläge für Mini-Schritte (optional)

1. Edge Functions → Deploy a new function → Via Editor → Name `suggest-step`,
   Inhalt von `supabase/functions/suggest-step/index.ts` → Deploy.
2. In den Einstellungen der Funktion „Verify JWT“ ausschalten (sie prüft die Anmeldung selbst).
3. Edge Functions → Secrets → `ANTHROPIC_API_KEY` (Schlüssel aus der Claude Console).

Modell: Claude Haiku 5.5. Höchstens 40 Vorschläge pro Person und Tag (`sp_take_quota`).
Ohne Konto, offline oder ohne Funktion zeigt die App allgemeine Ideen.

## Schnittstelle für ZbiWeb (optional)

1. `supabase-setup.sql` nochmals im SQL Editor ausführen (ergänzt Token-Tabelle, Prüffunktionen und die Spalte `rev`).
2. Edge Functions → Deploy a new function → Via Editor → Name **`api`**,
   Inhalt von `supabase/functions/api/index.ts` → Deploy.
3. In den Einstellungen der Funktion **„Verify JWT“ ausschalten**. Die Funktion prüft den API-Token selbst;
   mit eingeschalteter Prüfung lehnt Supabase jeden Aufruf mit 401 ab. Secrets braucht diese Funktion keine.
4. App → Einstellungen → Schnittstelle → Einrichten → „Token erzeugen“ → „Token kopieren“.
5. In ZbiWeb: Token im Tresor unter `speicherpunkt.token` ablegen, die Tür für
   `https://satqwruqmwgcflcggbul.supabase.co/functions/v1/api` freigeben und `SCHNITTSTELLE.md` als Vertrag hinterlegen.
6. Abnahme: die Schritte in `SCHNITTSTELLE.md`, Abschnitt 12, oder kurz:

       curl -s -H "Authorization: Bearer <TOKEN>" https://satqwruqmwgcflcggbul.supabase.co/functions/v1/api/

   Antwort `{"schnittstelle":"speicherpunkt","version":2}` heisst: alles eingerichtet.

Fehlt Schritt 1, zeigt die App unter „Schnittstelle“ einen Hinweis. Die App selbst funktioniert auch ohne
Schritt 1 weiter (Abgleich wie bisher, nur ohne Schutz vor gleichzeitigem Schreiben).

## Tests

    cd entwicklung/tests
    ./run_all.sh            # testet die App zwei Ordner weiter oben

Braucht Python 3 mit Playwright (Chromium) und Node.js. Supabase wird durch `mock_supabase.py` ersetzt.
`test_api.py` braucht zusätzlich Postgres und PostgREST (`POSTGREST=/pfad/zu/postgrest ./run_all.sh`), sonst wird er übersprungen.
