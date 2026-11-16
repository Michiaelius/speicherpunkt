# Tests

`./run_all.sh` startet die App in einem echten Browser (Chromium über Playwright) und klickt sich durch:

- `test_web.py` – Bedienung auf Handy und PC, hell und dunkel, Offline-Start, Installierbarkeit
- `test_sync.py` – Konten, Abgleich zwischen Geräten, zwei Personen, KI-Vorschläge
- `test_robust.py` – kaputte Daten, gelöschte Projekte, Abmelden ohne Netz, zwei Tabs
- `test_auth.py` – Passwort vergessen, Links aus E-Mails
- `test_features.py` – Fokus-Timer, Kalendereintrag, Belohnung, Wochenzähler
- `test_pages.py` – Landingpage mit Warteliste, Datenschutz, Impressum, Konto löschen
- `fntest/run.mjs` – die Edge Function `suggest-step` mit simulierten Antworten

`mock_supabase.py` spielt Supabase (Anmeldung, Datenbank, Edge Function) lokal nach.
