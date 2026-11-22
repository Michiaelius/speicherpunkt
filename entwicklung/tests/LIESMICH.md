# Tests

`./run_all.sh` startet die App in einem echten Browser (Chromium über Playwright) und klickt sich durch:

- `test_web.py` – Bedienung auf Handy und PC, hell und dunkel, Offline-Start, Installierbarkeit
- `test_sync.py` – Konten, Abgleich zwischen Geräten, zwei Personen, KI-Vorschläge
- `test_robust.py` – kaputte Daten, gelöschte Projekte, Abmelden ohne Netz, zwei Tabs
- `test_auth.py` – Passwort vergessen, Links aus E-Mails
- `test_features.py` – Fokus-Timer, Kalendereintrag, Belohnung, Wochenzähler
- `test_pages.py` – Landingpage mit Warteliste, Datenschutz, Impressum, Konto löschen
- `test_push.py` – Erinnerungen einschalten, abmelden, anderes Konto, Probe, Service Worker, anonyme Zählung
- `fntest/run.mjs` – die Edge Function `suggest-step` mit simulierten Antworten
- `fntest/push_run.mjs` – die Edge Function `push`: Verschlüsselung (RFC 8291) und Ausweis (VAPID) werden unabhängig nachgeprüft
- `test_db.py` – App und Datenbank zusammen, gegen echtes Postgres und PostgREST (dieselbe Software wie bei Supabase):
  Zugriffsregeln, Revisionszähler, gleichzeitiges Schreiben zweier Geräte, ältere Datenbank ohne `rev`,
  Aufräumen der Schnittstelle aus Version 8, Konto löschen, Regeln für Erinnerungen und Zählung.
  Braucht Postgres (initdb, pg_ctl, psql) und PostgREST 12 (`POSTGREST=/pfad/zu/postgrest`), sonst übersprungen.

`mock_supabase.py` spielt Supabase (Anmeldung, Datenbank, Edge Function) lokal nach.
`lokal_supabase.py` startet für `test_db.py` ein echtes Postgres mit PostgREST (`supabase_stub.sql` ersetzt die Supabase-eigenen Teile).
