# Tests

`./run_all.sh` startet die App in einem echten Browser (Chromium über Playwright) und klickt sich durch:

- `test_web.py` – Bedienung auf Handy und PC, hell und dunkel, Offline-Start, Installierbarkeit
- `test_sync.py` – Konten, Abgleich zwischen Geräten, zwei Personen, KI-Vorschläge
- `test_robust.py` – kaputte Daten, gelöschte Projekte, Abmelden ohne Netz, zwei Tabs
- `test_auth.py` – Passwort vergessen, Links aus E-Mails
- `test_features.py` – Fokus-Timer, Kalendereintrag, Belohnung, Wochenzähler
- `test_pages.py` – Landingpage mit Warteliste, Datenschutz, Impressum, Konto löschen
- `fntest/run.mjs` – die Edge Function `suggest-step` mit simulierten Antworten
- `fntest/api_run.mjs` – die Edge Function `api` (Schnittstelle für ZbiWeb), über 70 Fälle
- `test_api.py` – Schnittstelle, App und Datenbank zusammen, gegen echtes Postgres und PostgREST
  (dieselbe Software wie bei Supabase): Zugriffsregeln, Ratenbegrenzung, Abnahme aus `SCHNITTSTELLE.md`,
  Token in der App, gleichzeitiges Schreiben von App und Schnittstelle, ältere Datenbank ohne `rev`.
  Braucht Postgres (initdb, pg_ctl, psql) und PostgREST 12 (`POSTGREST=/pfad/zu/postgrest`), sonst übersprungen.

`mock_supabase.py` spielt Supabase (Anmeldung, Datenbank, Edge Function) lokal nach.
`lokal_supabase.py` startet für `test_api.py` ein echtes Postgres mit PostgREST (`supabase_stub.sql` ersetzt die Supabase-eigenen Teile).
