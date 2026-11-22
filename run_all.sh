#!/bin/bash
# Führt alle Tests aus. Aufruf: ./run_all.sh [app-ordner] [ausgabeordner]
# Standard: die App zwei Ordner weiter oben, Ausgaben in einem temporären Ordner.
cd "$(dirname "$0")"
APP=$(cd "${1:-../..}" && pwd); OUT=${2:-${TMPDIR:-/tmp}/speicherpunkt-tests}
fail=0
run() {
  echo "== $1 =="
  timeout "$2" python3 "$3" "$APP" "$OUT/$4" ${5:-} > "$OUT-$4.log" 2>&1
  if grep -q "ALL OK" "$OUT-$4.log"; then echo OK
  elif grep -q "ÜBERSPRUNGEN" "$OUT-$4.log"; then grep "ÜBERSPRUNGEN" "$OUT-$4.log" | head -1
  else echo "FEHLER (siehe $OUT-$4.log)"; tail -20 "$OUT-$4.log"; fail=1; fi
}
mkdir -p "$OUT"
run "Bedienung (Handy, PC, hell, dunkel)" 900 test_web.py web Europe/Zurich
run "Abgleich und Vorschläge" 600 test_sync.py sync
run "Robustheit" 300 test_robust.py robust
run "Passwort und E-Mail-Links" 300 test_auth.py auth
run "Timer, Kalender, Belohnung" 300 test_features.py features
run "Landingpage, Rechtstexte, Konto löschen" 300 test_pages.py pages
# Braucht Postgres und PostgREST (Umgebungsvariable POSTGREST), sonst übersprungen
run "Abgleich mit echter Datenbank" 600 test_db.py db
echo "== Edge Function suggest-step =="
cp "$APP/supabase/functions/suggest-step/index.ts" fntest/fn.mjs
if (cd fntest && node run.mjs) | tee "$OUT-fn.log" | grep -q FAIL; then echo "FEHLER (siehe $OUT-fn.log)"; fail=1; else echo OK; fi
rm -f fntest/fn.mjs
if grep -l "BITTE ERGÄNZEN\|BITTE PRÜFEN" "$APP"/*.html "$APP"/willkommen/*.html >/dev/null 2>&1; then
  echo "Hinweis: In diesen Seiten fehlen noch Angaben (gelb markiert):"; grep -l "BITTE ERGÄNZEN\|BITTE PRÜFEN" "$APP"/*.html "$APP"/willkommen/*.html
fi
exit $fail
