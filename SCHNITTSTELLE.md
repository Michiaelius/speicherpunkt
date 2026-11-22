# Schnittstelle „Speicherpunkt“

**Vertrag zwischen ZbiWeb und der App „Speicherpunkt“** (speicherpunkt.zbinden.space).
ZbiWeb ruft diese Schnittstelle auf, die App antwortet genau so, wie hier beschrieben.
Stand: 19.11.2026, Version 2. Ersetzt Version 1 vom 12.11.2026.

## 0. Was sich gegenüber Version 1 ändert

| Version 1 | Version 2 | Grund |
|-----------|-----------|-------|
| Basis-URL `https://speicherpunkt.zbinden.space/api/v1` | `https://satqwruqmwgcflcggbul.supabase.co/functions/v1/api` | speicherpunkt.zbinden.space liegt auf GitHub Pages. Dort werden nur fertige Dateien ausgeliefert, ein Token lässt sich nicht prüfen. Die Schnittstelle läuft deshalb als Supabase Edge Function. |
| Einträge mit `titel`, `text`, `tags` | Projekte mit Speicherpunkten (`wo`, `naechster_schritt`) | Speicherpunkt ist kein Notizspeicher. Die App hält für jedes Projekt fest, wo man stehen geblieben ist und was der nächste Mini-Schritt ist. |
| Pfad `/eintraege` | `/projekte` und `/projekte/{id}/speicherpunkte` | wie oben |
| ein einziges Konto | mehrere Konten (z. B. Michael und seine Frau) | Der Token gilt nur für das Konto, in dem er erzeugt wurde. Fremde Konten sind nicht erreichbar, deshalb gibt es kein 403. |

**Für ZbiWeb heisst das:** Die Tür muss `satqwruqmwgcflcggbul.supabase.co` erlauben (nur Pfade unter
`/functions/v1/api`) statt `speicherpunkt.zbinden.space`. Der Tresor-Eintrag `speicherpunkt.token` bleibt.

## 1. Zweck

ZbiWeb soll Michaels Projekte in der App „Speicherpunkt“ lesen, durchsuchen, anlegen, ändern und löschen
und für ein Projekt einen neuen Speicherpunkt setzen. Typische Fragen, die ZbiWeb damit beantwortet:
„Wo war ich bei X stehen geblieben?“, „Was steht an?“. Typische Aufträge: „Speichere bei X: bin bei …,
als Nächstes …“.

Ein **Speicherpunkt** besteht aus zwei Teilen:

- **wo**: wo man stehen geblieben ist, ein oder zwei Sätze.
- **naechster_schritt**: der nächste Mini-Schritt, so klein, dass man sofort anfangen kann.

Jedes Projekt hat immer einen aktuellen Speicherpunkt, nämlich den neuesten.

## 2. Basis-URL

```
https://satqwruqmwgcflcggbul.supabase.co/functions/v1/api
```

Alle Pfade in diesem Dokument sind relativ zu dieser Basis-URL.

## 3. Authentifizierung

Jeder Aufruf, auch jeder Lesezugriff, braucht den API-Token im HTTP-Header:

```
Authorization: Bearer <TOKEN>
```

- **Token erzeugen:** In der App unter Einstellungen → Schnittstelle → Einrichten → „Token erzeugen“.
  Die App zeigt ihn genau einmal an. Michael trägt ihn im Tresor von ZbiWeb unter dem Namen `speicherpunkt.token` ein.
- **Format:** `sp_` gefolgt von 64 Kleinbuchstaben oder Ziffern (hex), zusammen 67 Zeichen.
- Die App speichert nur eine Prüfsumme (SHA-256) des Tokens, nie den Token selbst.
- Der Token erscheint nie in Antworten, Dateien oder Logs. Die Tür setzt ihn selbst in den Header ein.
- Fehlender, falscher oder gelöschter Token: HTTP 401.
- **Token ersetzen:** In der App „Neuen Token erzeugen“. Der alte Token wird sofort ungültig.
- **Token sperren:** In der App „Token löschen“. Danach antwortet die Schnittstelle mit 401.
- Die App zeigt an, wann der Token zuletzt benutzt wurde.

## 4. Datenformat

Alle Antworten sind JSON mit `Content-Type: application/json; charset=utf-8`.
Alle Zeitpunkte sind ISO 8601 in UTC mit `Z`, zum Beispiel `2026-11-19T07:30:00Z`.

### 4.1 Projekt

```json
{
  "id": "k3j2h1g0f9e8",
  "name": "Gartenhaus streichen",
  "status": "aktiv",
  "faellig": false,
  "erinnerung": "2026-11-22T07:00:00Z",
  "erstellt": "2026-11-12T10:30:00Z",
  "geaendert": "2026-11-19T07:30:00Z",
  "abgeschlossen": null,
  "speicherpunkt": {
    "id": "a8d7c6b5e4f3",
    "wo": "Die Südwand ist fertig grundiert. Bei der Tür fehlt noch Klebeband.",
    "naechster_schritt": "Klebeband um den Türrahmen kleben",
    "erledigt": false,
    "erledigt_am": null,
    "gespeichert": "2026-11-19T07:30:00Z",
    "abschluss": false
  },
  "anzahl_speicherpunkte": 2
}
```

| Feld | Typ | Bedeutung |
|------|-----|-----------|
| id | string | Von der App vergeben, nicht änderbar. Meist 12 Zeichen (a–z, 0–9). Ältere Projekte können eine andere Form haben, also nie selbst prüfen oder erzeugen. |
| name | string | Name des Projekts, höchstens 80 Zeichen. |
| status | string | `aktiv`, `ruht` (bewusst pausiert) oder `fertig` (abgeschlossen). |
| faellig | bool | `true`, wenn die Erinnerung erreicht ist und das Projekt aktiv ist. Die App zeigt solche Projekte zuoberst. |
| erinnerung | string oder null | Wann die App an das Projekt erinnert. |
| erstellt | string | Wann das Projekt angelegt wurde. |
| geaendert | string | Letzte Änderung, auch aus der App. |
| abgeschlossen | string oder null | Wann das Projekt abgeschlossen wurde. |
| speicherpunkt | Objekt oder null | Der aktuelle (neueste) Speicherpunkt, siehe 4.2. |
| anzahl_speicherpunkte | int | Wie viele Speicherpunkte das Projekt hat. |
| verlauf | Liste | Nur beim Lesen eines einzelnen Projekts: alle Speicherpunkte, neueste zuerst. |

### 4.2 Speicherpunkt

| Feld | Typ | Bedeutung |
|------|-----|-----------|
| id | string | Von der App vergeben. |
| wo | string | Wo man stehen geblieben ist, höchstens 1000 Zeichen. Darf leer sein. |
| naechster_schritt | string | Der nächste Mini-Schritt, höchstens 200 Zeichen. |
| erledigt | bool | `true`, wenn dieser Schritt erledigt wurde. |
| erledigt_am | string oder null | Wann er erledigt wurde. |
| gespeichert | string | Wann der Speicherpunkt gesetzt wurde. |
| abschluss | bool | `true` beim Abschluss-Eintrag eines fertigen Projekts. |

## 5. Endpunkte

### 5.0 Verbindung prüfen

```
GET /
```

Antwort 200: `{ "schnittstelle": "speicherpunkt", "version": 2 }`

### 5.1 Projekte auflisten und suchen

```
GET /projekte
GET /projekte?suche=Steuer&status=aktiv&limit=5
```

| Parameter | Typ | Bedeutung |
|-----------|-----|-----------|
| suche | string | Sucht in Name, `wo` und `naechster_schritt` aller Speicherpunkte. Mehrere Wörter: alle müssen vorkommen. Gross- und Kleinschreibung egal. Leer = alle. |
| status | string | `alle` (Standard), `aktiv`, `ruht` oder `fertig`. |
| limit | int | Höchstens so viele Projekte. Standard 20, höchstens 100 (grössere Werte gelten als 100). |

Antwort 200:

```json
{ "projekte": [ { "id": "…", "name": "…", "status": "aktiv", "speicherpunkt": { … }, … } ], "anzahl": 1 }
```

- Sortierung: `geaendert` absteigend (zuletzt bearbeitet zuerst).
- `anzahl` = Anzahl Projekte in dieser Antwort.
- In der Liste fehlt `verlauf`, dafür gibt es 5.2.
- Antwort 422: `status` oder `limit` ungültig.

### 5.2 Ein Projekt lesen

```
GET /projekte/{id}
```

Antwort 200: das Projekt mit `verlauf` (alle Speicherpunkte, neueste zuerst).
Antwort 404: Das Projekt gibt es nicht (oder es wurde gelöscht).

### 5.3 Ein Projekt anlegen

```
POST /projekte
Content-Type: application/json; charset=utf-8
```

```json
{
  "name": "Steuererklärung 2026",
  "naechster_schritt": "Lohnausweis im Ordner suchen",
  "wo": "Noch nichts gemacht",
  "erinnerung": "2026-11-22T08:00:00+01:00"
}
```

| Feld | Pflicht | Bedeutung |
|------|---------|-----------|
| name | ja | höchstens 80 Zeichen |
| naechster_schritt | ja | Der erste Mini-Schritt, höchstens 200 Zeichen. Jedes Projekt braucht einen. Weiss Michael noch keinen, schlägt ZbiWeb einen kleinen vor und fragt nach. |
| wo | nein | höchstens 1000 Zeichen |
| erinnerung | nein | ISO 8601 **mit Uhrzeit und Zeitzone**, oder `null` |

- `id`, `erstellt` und andere Felder setzt die App. Mitgeschickte Werte werden ignoriert.

Antwort 201: das neue Projekt mit `verlauf`.
Antwort 400: `name` oder `naechster_schritt` fehlt oder ist leer, oder der Körper ist kein JSON-Objekt.
Antwort 409: Es gibt schon ein **offenes** (nicht abgeschlossenes) Projekt mit diesem Namen. Die Antwort enthält dessen `id`:
`{ "fehler": "…", "id": "k3j2h1g0f9e8" }`. Das schützt vor doppeltem Anlegen, etwa wenn ZbiWeb einen Aufruf wiederholt.
Antwort 422: Ein Feld ist zu lang oder hat das falsche Format.

### 5.4 Ein Projekt ändern

```
PATCH /projekte/{id}
Content-Type: application/json; charset=utf-8
```

Körper: nur die Felder, die sich ändern. Mindestens eines ist Pflicht.

| Feld | Bedeutung |
|------|-----------|
| name | umbenennen |
| status | `aktiv` (aufwecken), `ruht` (ruhen lassen) oder `fertig` (abschliessen). `ruht` und `fertig` löschen die Erinnerung. |
| erinnerung | ISO 8601 mit Zeitzone, oder `null` zum Löschen |
| naechster_schritt | Den aktuellen Schritt umformulieren, zum Beispiel kleiner machen. Legt keinen neuen Speicherpunkt an. |
| abschluss_notiz | Nur zusammen mit `"status": "fertig"`. Hält fest, wie das Projekt geendet hat, und hakt den letzten Schritt ab. |

Beispiele: `{ "status": "ruht" }`, `{ "naechster_schritt": "Nur den Ordner öffnen" }`,
`{ "status": "fertig", "abschluss_notiz": "Eingereicht am 19.11." }`

Antwort 200: das geänderte Projekt mit `verlauf`.
Antwort 400: kein änderbares Feld im Körper.
Antwort 404: das Projekt gibt es nicht.
Antwort 409: Die Änderung passt nicht zum Zustand, zum Beispiel ein abgeschlossenes Projekt auf `aktiv` setzen.
Ein abgeschlossenes Projekt öffnet man wieder, indem man einen neuen Speicherpunkt setzt (5.6).
Antwort 422: ein Feld hat das falsche Format.

### 5.5 Ein Projekt löschen

```
DELETE /projekte/{id}
```

Antwort 204: gelöscht, kein Körper. Das Projekt verschwindet auch auf allen Geräten.
Antwort 404: das Projekt gibt es nicht.

### 5.6 Einen Speicherpunkt setzen

Das ist die wichtigste Funktion: festhalten, wo Michael steht und was als Nächstes kommt.

```
POST /projekte/{id}/speicherpunkte
Content-Type: application/json; charset=utf-8
```

```json
{
  "wo": "Lohnausweis gefunden, liegt auf dem Pult.",
  "naechster_schritt": "Formular auf der Steuer-Website öffnen",
  "letzter_erledigt": true,
  "erinnerung": "2026-11-21T08:00:00+01:00"
}
```

| Feld | Pflicht | Bedeutung |
|------|---------|-----------|
| naechster_schritt | ja | höchstens 200 Zeichen |
| wo | nein | höchstens 1000 Zeichen |
| letzter_erledigt | nein | `true`: Der bisherige Schritt ist erledigt und wird abgehakt. Standard `false` (unterbrochen, nicht erledigt). |
| erinnerung | nein | Neue Erinnerung. **Ohne dieses Feld wird eine bisherige Erinnerung gelöscht**, weil sie zum alten Schritt gehörte. |

- Ein ruhendes oder abgeschlossenes Projekt wird dabei wieder aktiv.

Antwort 201: das Projekt mit dem neuen Speicherpunkt und `verlauf`.
Antwort 400: `naechster_schritt` fehlt oder ist leer.
Antwort 404: das Projekt gibt es nicht.
Antwort 422: ein Feld hat das falsche Format.

### 5.7 Verlauf eines Projekts

```
GET /projekte/{id}/speicherpunkte
```

Antwort 200: `{ "speicherpunkte": [ … ], "anzahl": 3 }`, neueste zuerst.

## 6. Fehlercodes

Alle Fehlerantworten sind JSON:

```json
{ "fehler": "kurze Beschreibung auf Deutsch" }
```

| Code | Bedeutung |
|------|-----------|
| 400 | Aufruf unvollständig: Pflichtfeld fehlt oder ist leer, kein änderbares Feld, kein gültiges JSON. |
| 401 | Token fehlt, ist falsch, wurde ersetzt oder gelöscht. |
| 404 | Projekt oder Pfad gibt es nicht. |
| 405 | Methode an diesem Pfad nicht erlaubt. Der Header `Allow` nennt die erlaubten. |
| 409 | Konflikt: doppelter Name beim Anlegen, Änderung passt nicht zum Zustand, oder gleichzeitige Änderungen (dann einfach nochmals versuchen). |
| 413 | Körper grösser als 64 KB. |
| 422 | Ein Feld hat das falsche Format oder ist zu lang. |
| 429 | Zu viele Aufrufe, siehe Abschnitt 7. |
| 500 | Fehler in der App oder Datenbank nicht eingerichtet. |
| 503 | Datenbank gerade nicht erreichbar. Später nochmals versuchen. |

## 7. Rate-Limits

- Höchstens 60 Aufrufe pro Minute pro Token.
- Bei Überschreitung: HTTP 429 mit Header `Retry-After` (Sekunden bis zur nächsten Minute).
- ZbiWeb plant seine Aufrufe so, dass es dieses Limit nicht erreicht.

## 8. Zusammenspiel mit der App

- Änderungen über die Schnittstelle landen sofort in Michaels Konto. Die App zeigt sie beim nächsten Abgleich:
  beim Öffnen, beim Zurückwechseln in die App und jede Minute, solange sie offen ist.
- Schreiben App und Schnittstelle gleichzeitig, geht nichts verloren: Wer zu spät kommt, liest neu und führt zusammen.
- Ändern beide **dasselbe Projekt** fast gleichzeitig, gilt pro Projekt die neuere Änderung.
- Die App zeigt höchstens 80 Zeichen Name und 200 Zeichen Schritt. Die Grenzen der Schnittstelle sind gleich.

## 9. Beispiel-Aufrufe

```bash
B="https://satqwruqmwgcflcggbul.supabase.co/functions/v1/api"

# Was steht an? Die fünf zuletzt bearbeiteten aktiven Projekte
curl -s -H "Authorization: Bearer <TOKEN>" "$B/projekte?status=aktiv&limit=5"

# Wo war ich bei den Steuern?
curl -s -H "Authorization: Bearer <TOKEN>" "$B/projekte?suche=steuer"

# Projekt anlegen
curl -s -X POST -H "Authorization: Bearer <TOKEN>" -H "Content-Type: application/json; charset=utf-8" \
  -d '{"name":"Steuererklärung 2026","naechster_schritt":"Lohnausweis im Ordner suchen"}' "$B/projekte"

# Speicherpunkt setzen, letzter Schritt erledigt
curl -s -X POST -H "Authorization: Bearer <TOKEN>" -H "Content-Type: application/json; charset=utf-8" \
  -d '{"wo":"Lohnausweis liegt auf dem Pult","naechster_schritt":"Formular öffnen","letzter_erledigt":true}' \
  "$B/projekte/k3j2h1g0f9e8/speicherpunkte"

# Ruhen lassen
curl -s -X PATCH -H "Authorization: Bearer <TOKEN>" -H "Content-Type: application/json; charset=utf-8" \
  -d '{"status":"ruht"}' "$B/projekte/k3j2h1g0f9e8"

# Löschen
curl -s -X DELETE -H "Authorization: Bearer <TOKEN>" "$B/projekte/k3j2h1g0f9e8"
```

## 10. Typische Aufträge an ZbiWeb

| Michael sagt | ZbiWeb ruft auf |
|--------------|-----------------|
| „Wo war ich bei X?“ | `GET /projekte?suche=X`, dann `speicherpunkt.wo` und `speicherpunkt.naechster_schritt` vorlesen. |
| „Was steht an?“ | `GET /projekte?status=aktiv&limit=5`, fällige (`faellig: true`) zuerst nennen. |
| „Speichere bei X: bin bei …, als Nächstes …“ | Projekt suchen, dann `POST /projekte/{id}/speicherpunkte`. |
| „Hab den Schritt bei X erledigt, jetzt kommt …“ | dasselbe mit `"letzter_erledigt": true`. |
| „Der Schritt ist mir zu gross.“ | `PATCH /projekte/{id}` mit kleinerem `naechster_schritt`. |
| „Neues Projekt X.“ | `POST /projekte`. Ohne genannten ersten Schritt einen kleinen vorschlagen und bestätigen lassen. |
| „Lass X ruhen.“ / „X ist fertig.“ | `PATCH /projekte/{id}` mit `status`. |
| „Erinnere mich morgen an X.“ | `PATCH /projekte/{id}` mit `erinnerung` (Uhrzeit mit Zeitzone, z. B. 08:00 Europe/Zurich). |

Findet die Suche mehrere Projekte, fragt ZbiWeb nach, statt zu raten.

## 11. Anbindung an ZbiWeb

- ZbiWeb ruft die Schnittstelle über die Tür auf (zbiweb/tuer). Lesen geht ohne Freigabe-Karte.
  Anlegen, Ändern, Speicherpunkt setzen und Löschen brauchen Michaels Ja auf einer Freigabe-Karte (Core 3).
- Der Token liegt im Tresor unter `speicherpunkt.token`, freigegeben für `tuer`. Die Tür setzt ihn
  in den Header ein. Er erscheint nie in einer Antwort, Datei oder einem Log.
- ZbiWeb ruft nur `https://satqwruqmwgcflcggbul.supabase.co/functions/v1/api…` auf. Jede andere Adresse wird abgelehnt,
  auch andere Pfade auf demselben Host.

## 12. Abnahme

Die Anbindung ist fertig, wenn:

1. `GET /projekte` ohne Token 401 liefert, mit Token 200 mit `projekte` und `anzahl`.
2. `POST /projekte` mit `{"name":"Abnahme ZbiWeb","naechster_schritt":"Test durchführen"}` 201 mit dem neuen Projekt liefert.
3. `GET /projekte/{id}` für die neue id 200 mit dem Projekt liefert.
4. `PATCH /projekte/{id}` mit `{"name":"Abnahme ZbiWeb x"}` 200 mit dem geänderten Projekt liefert.
5. `POST /projekte/{id}/speicherpunkte` mit `{"naechster_schritt":"Aufräumen","letzter_erledigt":true}` 201 liefert, mit `anzahl_speicherpunkte` 2.
6. `DELETE /projekte/{id}` 204 liefert.
7. `GET /projekte/{id}` danach 404 liefert.

Das Testprojekt erscheint zwischendurch kurz in der App und verschwindet nach Schritt 6 wieder.
