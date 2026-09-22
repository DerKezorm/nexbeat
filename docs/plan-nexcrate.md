# Plan: nexcrate als Ziel fuer Anfragen

Stand 22.09.2026. nexbeat fragt heute nur bei Lidarr an. nexcrate ersetzt Radarr, Sonarr und Lidarr und hat eine
feste Schnittstelle fuer andere Programme (`/api/v1`, Vertrag 1, Etappe V5 mit Musik). nexbeat ist ihr erster
Verbraucher.

## Entscheidungen

| Frage | Antwort | Folge |
|---|---|---|
| Lidarr, nexcrate oder beides | **Ein Modus je Installation**, der Admin waehlt: ARR-Modus (Lidarr) oder NEX-Modus (nexcrate) | Bestand, Abzeichen und Anfragen kommen aus genau einer Quelle. Eine bestehende Installation mit Lidarr bleibt im ARR-Modus, ohne dass jemand etwas tun muss |
| Was bei „Ganzer Kuenstler“ angefragt wird | **Nur Studioalben**, wie heute bei Lidarr | `{"artist": {"albums": "studio", "types": ["studio"]}}`, kuenftige Studioalben kommen mit |
| Wie nexbeat den Stand erfaehrt | **Ereignisstrom weckt, Abgleich zaehlt** | nexbeat haelt `/api/v1/events/stream` offen und weckt bei Musik-Ereignissen den Abgleich. Der Abgleich fragt nexcrate mit einem Stapel (`titles/lookup`). Ohne Strom laeuft der Abgleich wie heute alle zwei Minuten |
| Koppeln | **Koppeln per Bitte, Schluessel von Hand als Ausweg** | „Mit nexcrate verbinden“ schickt `POST /api/v1/pairing`, zeigt den Code, holt den Schluessel ab. Wer das nicht will, fuegt einen Schluessel aus nexcrate ein |
| Name im Repo | nexcrate darf in `main` stehen, gepusht wird erst auf Wort | |

## Was nexbeat im NEX-Modus tut

- **Album anfragen:** `POST /api/v1/requests` mit `kind: album`, `ref: mbid:<release group>`,
  `origin: nexbeat:request:<nummer>`, `search_now: true`. Die Anfrage ist bei nexcrate idempotent ueber Art und
  Kennung. Eine Uebergabe mit offenem Ausgang (Zeitueberschreitung) wird deshalb im naechsten Abgleich einfach noch
  einmal gesendet; die Wartezeit von zehn Minuten wie bei Lidarr braucht es nicht.
- **Ganzen Kuenstler anfragen:** dieselbe Adresse mit `kind: artist` und der Wahl oben.
- **Stand:** ein Stapel `POST /api/v1/titles/lookup` fuer alle offenen Anfragen (bis 100 je Aufruf). Album: Zustand
  der einen Fassung, Fortschritt aus `album.tracks {have, total}`. Kuenstler: `artist.albums {watched, available,
  missing}`, fertig, wenn nichts Ueberwachtes mehr fehlt.
- **Bestand:** die Kuenstler aus `GET /api/v1/titles?kind=artist`, erst ganz, danach nur, was sich seit der Nummer
  geaendert hat (`after=`), samt `removed`. `410 marker_too_old` liest wieder ganz.
- **Abzeichen der Alben** auf Kuenstler- und Albumseite: `GET /api/v1/titles/artist/<ref>` liefert den Katalog mit dem
  Zustand je Album, fuenf Minuten im Zwischenspeicher wie bei Lidarr.
- **Nichts an nexcrate einstellen.** nexbeat legt keine Fassung, kein Profil, keinen Indexer an. Fehlt die
  Musik-Fassung oder ist sie nicht bereit, sagt nexbeat das in den Einstellungen und im Fehlertext.
- **Probelauf** gilt fuer beide Modi: angelegt und gezaehlt, nichts gesendet.
- **Metadatenprofil:** gibt es in nexcrate nicht. Die Sperren aus Lidarrs Profil (Art ausgeschlossen, Profil zu weit)
  entfallen im NEX-Modus; welche Alben ein ganzer Kuenstler bringt, legt nexbeat mit `types` selbst fest.

## Was nicht gebaut wird (erste Runde)

- **Zuruecknehmen nach dem Senden.** nexcrate kann es (`withdraw`), nexbeat kann es heute auch bei Lidarr nicht. Eine
  eigene Entscheidung: `withdraw` am Kuenstler nimmt auch Alben zurueck, die ein anderer Benutzer einzeln wollte.
- **Warteschlange und „warum noch nicht da“** in der Oberflaeche. Die Adressen gibt es, nexbeat zeigt sie noch nicht.
- **Umzug erledigter Anfragen.** Beim Umschalten reicht der Abgleich nur offene Anfragen nach (siehe „Gebaut“).
  Geladene und gescheiterte bleiben, wie sie sind.

## Gemessen (22.09.2026, Wegwerf-nexcrate 0.1.0, Vertrag V5, lokal, ohne Indexer und Download-Programm)

- `system`, `versions`, `lookup`, eine Einzelansicht: 14 bis 30 ms.
- Album anfragen, das nexcrate nicht kennt: 115 ms, wenn MusicBrainz' Antwort schon im Speicher lag, sonst 0,4 bis
  1,7 s. Ganzer Kuenstler, unbekannt: 1,6 s, den Katalog (21 Alben) hatte nexcrate nach unter 10 s geladen.
- Ereignisstrom: `request.withdrawn` kam 1,5 s nach dem Aufruf, `title.changed` und `version.removed` nach 8,7 s
  (Takt der Aenderungsmarke, 10 s). Alle 15 s ein Kommentar als Lebenszeichen.
- Grenze je Schluessel: 150 Aufrufe auf einmal alle 200, 300 auf einmal 44 mal `429 rate_limited` mit
  `Retry-After: 1`.
- Koppeln: Bitte in 16 ms, der Schluessel kommt genau einmal (`confirmed`), danach `delivered` ohne Schluessel.

Die Einzelheiten und alles, was am Vertrag auffiel, stehen ausserhalb des Repos in den Notizen zum Pruefstand.

## Gebaut (22.09.2026)

- **Modus:** Einstellung `request_mode` (`arr`, `nex`). Leer und Lidarr eingetragen gilt als ARR-Modus, eine
  bestehende Installation merkt also nichts. `lidarr.client_for` gibt im NEX-Modus nichts her, Lidarr bekommt dann
  nicht einmal eine Lesefrage (Test). `/api/auth/me` nennt `request_target`, die Texte der Oberflaeche nennen das
  Ziel ("nexcrate sucht").
- **Umschalten:** Zwischenspeicher, Bestand und Marke werden verworfen, der Strom verbindet neu. Offene Anfragen, die
  vor dem Wechsel ans andere Ziel gingen, reicht der Abgleich einmal nach (`request_mode_changed_at`), in beide
  Richtungen. Wer im ARR-Modus nur eine nexcrate eintraegt, verliert den Bestand aus Lidarr nicht.
- **nexcrate:** `services/nexcrate.py` (Client, Fehler in drei Koerben, `album_view`), `services/nexcrate_events.py`
  (Strom als Wecker, neu verbinden nach Fehler in 30 s und nach nexcrates Stunde sofort), `library.py` (Kuenstler ueber
  die Marke, mit `installation_id`; ganz lesen beim ersten Mal, einmal am Tag, bei `410`, bei fremder Marke),
  `requests_service.py` (senden, im Stapel nachsehen, offene einfach noch einmal senden).
- **Einstellungen:** Reiter Dienste, Ziel: Moduswahl, darunter Lidarr wie bisher oder nexcrate mit Koppeln (Code gross,
  Restzeit, Abbrechen), Schluessel von Hand, Bereitschaft der Musik-Fassung, Probelauf, Bestand und Ereignisse.
  Adressen `POST/GET/DELETE /api/settings/nexcrate/pairing`, `GET /api/settings/nexcrate/status`,
  `POST /api/settings/test/nexcrate`.

## Geprueft

- `tests/test_nexcrate.py` (43) gegen eine Attrappe auf HTTP-Ebene (`tests/fake_nexcrate.py`, nach den gemessenen
  Antworten). 16 Mutationen auf einer Kopie, alle gefangen; zwei erst nach geschaerften Faellen fuer `album_view`.
- vitest `AdminNexcrateSettings.test.tsx` (8): Koppeln bis zum Schluessel, Ablehnung, Bereitschaft ohne "Automatik
  aus" als Sperre, Schluessel von Hand, Umschalten, Zielname. 5 Mutationen auf einer Kopie, alle gefangen.
- Volle Reihe: 191 pytest, 31 vitest, ruff, eslint, Bau gruen.
- Durchlauf Wegwerf-nexbeat gegen Wegwerf-nexcrate: Koppeln (bestaetigt im Pruefstand direkt in nexcrates Datenbank),
  Albumanfrage in 1,0 s, ganzer Kuenstler in 3,0 s, Strom verbunden, Bestand ueber die Marke, Albumseite zeigt
  "nexcrate sucht".

## Was fehlt

| Was | Warum |
|---|---|
| Nie gegen echte Musik geladen | Die Wegwerf-Instanz hat weder Indexer noch Download-Programm. "geladen" ist nur mit der Attrappe getestet |
| Bestaetigen in nexcrates Oberflaeche nicht gesehen | Im Pruefstand wurde direkt in der Datenbank bestaetigt; kein Konto, kein Passwort |
| Zuruecknehmen nach dem Senden | wie bei Lidarr nicht gebaut; eigene Entscheidung (siehe oben) |
| Warteschlange und "warum noch nicht da" | die Adressen gibt es, nexbeat zeigt sie nicht |
| Luecken im Vertrag | stehen ausserhalb des Repos in den Notizen zum Pruefstand; nexcrate selbst ist unveraendert |
