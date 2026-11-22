# Änderungen

## Version 10 (22. November 2026)

Neu
- **Erinnerungen als Mitteilung:** Wer in den Einstellungen „Erinnerungen einschalten“ wählt, bekommt am Morgen der gewählten
  Erinnerung eine Mitteilung mit dem nächsten Mini-Schritt, auch wenn die App geschlossen ist. Ein Tipp darauf öffnet das Projekt.
  Mit Probe-Mitteilung, die den ganzen Weg über den Server prüft. Auf dem iPhone nur, wenn die App installiert ist.
- **Anonyme Zählung:** Die App merkt sich mit einer zufälligen Gerätenummer, an welchen Tagen sie geöffnet wird.
  Die Auswertung `sp_wiederkehr` zeigt, wie viele nach einer und nach zwei Wochen wiederkommen. In den Einstellungen abschaltbar.
- Anleitung für den eigenen E-Mail-Absender (SMTP) in `LIESMICH.md`.

Einrichten: `supabase-setup.sql` nochmals ausführen und die Edge Function `push` anlegen (siehe `LIESMICH.md`).
Ohne das läuft die App wie bisher weiter; unter „Erinnerungen“ steht dann, dass der Server noch nicht bereit ist.

## Version 9 (22. November 2026)

- **Schnittstelle für andere Programme wieder entfernt.** Die Anbindung an ZbiWeb passt nicht zu dessen Konzept.
  Der Kasten „Schnittstelle“ in den Einstellungen, die Edge Function `api`, `SCHNITTSTELLE.md` und der Absatz
  in der Datenschutzerklärung sind weg. `supabase-setup.sql` räumt die Token-Tabelle und ihre Funktionen auf.
- **Geblieben** aus Version 8: der Schutz vor gleichzeitigem Schreiben zwischen Geräten (`rev`) und
  der Abgleich, der nur noch schreibt, wenn sich wirklich etwas geändert hat.
- Diese Datei heisst jetzt `AENDERUNGEN.md` (ohne Umlaut), weil der Name beim Hochladen auf GitHub kaputtging.

## Version 8 (19. November 2026)

Neu
- **Schnittstelle für eigene Programme** (zum Beispiel ZbiWeb): Projekte lesen, suchen, anlegen, ändern, löschen
  und Speicherpunkte setzen. Beschreibung in `SCHNITTSTELLE.md`, Code in `supabase/functions/api/`.
- In den Einstellungen unter „Schnittstelle“: API-Token erzeugen, kopieren, ersetzen und löschen,
  mit Anzeige, wann er zuletzt benutzt wurde. Der Token wird nur einmal angezeigt und nur als Prüfsumme gespeichert.
  Höchstens 60 Aufrufe pro Minute.

Verbessert
- **Kein Datenverlust bei gleichzeitigem Schreiben:** Schreiben zwei Geräte oder App und Schnittstelle im selben Moment,
  liest die App neu und führt zusammen, statt die andere Änderung zu überschreiben (Revisionszähler `rev`).
- **Weniger unnötiges Schreiben:** Die App hat bisher bei fast jedem Abgleich die Daten neu hochgeladen, weil die
  Datenbank die Reihenfolge der Felder ändert. Jetzt liest sie nur, wenn sich nichts geändert hat.
- Datenschutzerklärung um die Schnittstelle ergänzt.
- Die Datenbankregeln werden jetzt gegen ein echtes Postgres mit PostgREST getestet, nicht nur gegen einen Nachbau.

## Version 7 (15. November 2026)

Neu
- **Landingpage mit Warteliste** unter /willkommen/: erklärt Speicherpunkt, fragt freiwillig „Was fällt dir beim Dranbleiben am schwersten?“
  und speichert, über welchen Link jemand kam (`?q=…`). Mit Vorschaubild für geteilte Links.
- **Datenschutzerklärung und Impressum**, verlinkt aus App, Landingpage und Anmeldung.
- **Konto löschen** in den Einstellungen: löscht Konto und alle Projekte, nach Eintippen von „löschen“.

## Version 6 (15. November 2026)

Neu
- **Fokus-Timer:** In „Nur das hier“ lässt sich ein Timer mit 5, 10 oder 25 Minuten starten.
  Der Bildschirm bleibt an, am Ende gibt es einen leisen Ton.
- **Erinnerung im Kalender:** Wer eine Erinnerung wählt, kann sie mit einem Tipp als Termin in den
  Kalender übernehmen. So meldet sich das Handy auch, wenn die App zu ist.
- **Passwort vergessen:** Link per E-Mail, danach neues Passwort direkt in der App setzen.
  Links aus Bestätigungs-E-Mails melden automatisch an.
- **Kleine Belohnung:** Bunte Kreise bei „Geschafft“ und beim Abschliessen
  (nicht bei „Bewegung reduzieren“). Auf der Startseite steht, wie viel in den letzten 7 Tagen geschafft wurde.
  Keine Serien, kein Druck: Wenn nichts geschafft wurde, steht dort nichts.
- Versionsnummer unten in den Einstellungen.

Verbessert
- Abmelden ohne Internet löscht keine ungesicherten Änderungen mehr. Die App warnt und bietet einen neuen Abgleich an.
- Mehrere offene Tabs melden sich nicht mehr gegenseitig ab.
- Wird ein Projekt auf einem anderen Gerät gelöscht, während es offen ist, stürzt nichts ab.
- Kaputte oder alte Daten (z. B. aus einer Sicherung) werden geprüft und repariert, statt die App zu blockieren.
- Wer ein Projekt hat, sieht auf der Startseite keine Erklärtexte mehr, sondern schneller den nächsten Schritt.
- Sicherheitsregeln (Content Security Policy): Die App darf nur mit sich selbst und mit Supabase sprechen.
- KI-Vorschläge: Zeitlimit und ein zweiter Versuch bei Überlastung.
- Bessere Fehlermeldungen bei der Anmeldung, Tastatur- und Screenreader-Bedienung nach Seitenwechseln.

## Version 5
- KI-Vorschläge für Mini-Schritte („Schritt vorschlagen“, „Kleinere Schritte vorschlagen“).

## Version 4
- Konten und Abgleich zwischen Geräten (Supabase).

## Version 3
- Gestaltung im Stil des Tagesplaners.

## Version 2
- Projekte abschliessen und wieder öffnen.

## Version 1
- Speicherpunkte, Rückkehr-Ansicht, Fokus-Modus, Ruhen lassen, Sicherung.
