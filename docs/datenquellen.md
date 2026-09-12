# Datenquellen, live geprueft

Stand 11.09.2026. Alles hier wurde gegen die echten Dienste gemessen, nicht aus
der Doku abgeschrieben. Wer eine Quelle neu anbindet, misst zuerst nach.

## MusicBrainz

- Suche: `GET https://musicbrainz.org/ws/2/artist?query=...&fmt=json`. Felder
  u. a. `id`, `name`, `type`, `country`, `disambiguation`, `score`, `tags`.
- Diskografie: `GET /ws/2/release-group?artist=<mbid>&type=album|ep|single&fmt=json`.
  Felder `id`, `title`, `primary-type`, `secondary-types`, `first-release-date`.
  `limit` hoechstens 100, mehr nur seitenweise. Bei einer Band mit vielen
  Mitschnitten hatten 90 von 100 Release-Groups vom Typ `album` einen Zusatztyp
  wie Live oder Compilation.
  - Ohne Filter kommen auch inoffizielle Release-Groups. Bei einem Duo waren es 48
    vom Typ `album`, mit `release-group-status=website-default` noch 23. Weg war
    etwa eine "Beta Version" (12.09.2026).
- Albumseite in einem Aufruf:
  `GET /ws/2/release?release-group=<mbid>&inc=recordings+artist-credits+release-groups&limit=25`
  liefert bis zu 25 Releases, jedes mit Titelliste und seiner Release-Group samt
  `artist-credit`. Beispiel: 25 von 39 Releases in 0,6 s.
- ⚠️ **Drosselt hart.** Bei zwei Anfragen im Abstand von 1,2 s kamen zweimal
  `503`, erst der dritte Versuch ging durch. Zu anderer Zeit kam die Suche
  dreimal hintereinander mit `503`, im Abstand von 2 s. Der Client braucht eine
  globale Grenze von einer Anfrage pro Sekunde, Wiederholung mit wachsender Pause
  und einen Zwischenspeicher. Nie beim Seitenaufruf in Schleifen abfragen.
  - Die Kopfzeilen sprechen fuer eine Grenze aller Nutzer zusammen:
    `X-RateLimit-Limit: 1200`, und `X-RateLimit-Remaining` sank binnen Sekunden
    um Hunderte, waehrend nexbeat vier Anfragen stellte. Die Suche meldete
    `X-RateLimit-Limit: 15` und antwortete `503` auch bei einem Rest von 10.
  - Eigens gedrosselt werden laut Wiki nur "anonyme" User-Agents: leer, `-`,
    `Java`, `Python-urllib`, `Jakarta Commons-HttpClient`, `Apache-HttpClient`.
    Der von nexbeat gehoert nicht dazu, ein anderer User-Agent hilft also nicht.
    Verlangt wird aber eine Kontaktmoeglichkeit darin, nexbeat nennt die Projektseite.
- Kennt kein Explicit-Kennzeichen.

## Cover Art Archive

- `GET https://coverartarchive.org/release-group/<mbid>/front-250` antwortet mit
  `307` und leitet nach archive.org weiter.
- ListenBrainz liefert `caa_id` und `caa_release_mbid` gleich mit, damit laesst
  sich die Bildadresse ohne Umweg bauen.

## ListenBrainz

- **Aehnliche Kuenstler:** `GET https://labs.api.listenbrainz.org/similar-artists/json`
  mit `artist_mbids` und Pflichtfeld `algorithm`, ohne Schluessel. Ein Kuenstler
  ergab 100 Zeilen mit `artist_mbid`, `name`, `score`, `reference_mbid`,
  `comment`, `gender`, `type`, jede Kennung einmal.
  - ⚠️ **Nur einzeln abfragen.** `artist_mbids` geht zwar mehrfach (mit Komma
    kommt `400`), die Antwort taugt dann aber nicht. Bei drei Kuenstlern kamen
    299 Zeilen: einer bekam 152 Zeilen fuer 100 Kuenstler, die anderen 90 von 99
    und 57 von 100. Zuordnung zum Ausgangskuenstler und Score stimmten dabei.
  - Gemessener Algorithmus:
    `session_based_days_7500_session_300_contribution_5_threshold_10_limit_100_filter_True_skip_30`.
    Die Formularseite `/similar-artists` listet sechs Varianten.
  - ⚠️ Labs heisst: Versuchsgelaende ohne Stabilitaetszusage.
- **Trends Kuenstler:** `GET https://api.listenbrainz.org/1/stats/sitewide/artists?count=&range=week`
  mit `artist_mbid`, `artist_name`, `listen_count`.
- **Trends Alben:** `GET /1/stats/sitewide/release-groups?count=&range=week` mit
  `release_group_mbid`, `release_group_name`, `artist_mbids`, `artist_name`,
  `caa_id`, `caa_release_mbid`, `listen_count`. ⚠️ Fuehrte zwei Alben je zweimal,
  mit derselben Kennung.
- **Beliebteste Alben eines Kuenstlers:**
  `GET /1/popularity/top-release-groups-for-artist/<mbid>` liefert eine Liste
  (bei einem Beispiel 307 Eintraege) mit `release_group_mbid`,
  `release_group{name, date, type, caa_id, caa_release_mbid}`,
  `total_listen_count`, `total_user_count`, `artist.artists[].artist_mbid`.
  ⚠️ Enthaelt auch fremde Release-Groups, auf denen der Kuenstler nur mitwirkt. Gemessen am
  12.09.2026: Bei einer Saengerin stammten sechs der ersten neun Alben von anderen Kuenstlern.
  nexbeat nimmt nur die, bei denen der Kuenstler selbst genannt ist.
  ⚠️ Seit 12.09.2026 teils nur mit Token: Fuer manche Kuenstler kam `401` mit dem
  Hinweis auf "bad actors and AI scrapers" und der Bitte um ein Auth-Token, fuer
  andere weiter `200` ohne. nexbeat meldet dann `listenbrainz_token_required` und
  blendet "Am meisten gehoert" aus. Die Wochenlisten und Labs gingen weiter ohne.

## Deezer

Tokenlos erreichbar, rechtlich Grauzone: Das Entwicklerportal vergibt seit etwa
Mitte 2025 keine Tokens mehr. Deshalb abschaltbar halten.

- `GET https://api.deezer.com/search/artist?q=<name>`: `id`, `name`, `nb_fan`,
  `picture_xl` u. a. Zuordnung zu MusicBrainz nur ueber den Namen.
- `GET /artist/<id>/related`: aehnliche Kuenstler mit Bildern.
- `GET /artist/<id>/top`: Titel mit `preview` (30 s) und `explicit_lyrics`.
- `GET /artist/<id>/albums?limit=100`: `title`, `record_type`
  (`album`, `ep`, `single`), `release_date`, `cover_xl`, `explicit_lyrics`.
  Alben ueber den Titel zuordnen, das traf im Test.
- `GET /album/<id>/tracks`: `preview`, `isrc`, `track_position`, `disk_number`.
- ⚠️ Die Albumsuche mit Operatoren (`artist:"..." album:"..."`) ergab im Test
  **0 Treffer**. Nicht verwenden.
- ⚠️ **Viele Anfragen auf einmal:** Beim ersten Aufbau der Startseite kamen binnen
  0,7 s 15 Ablehnungen, mit Status `200` und
  `{"error": {"type": "Exception", "message": "Quota limit exceeded", "code": 4}}`.
  nexbeat haelt deshalb 0,15 s Abstand.

## Last.fm

Nicht live getestet, es gibt noch keinen Schluessel. Aus den Nutzungsbedingungen:
frei nur fuer nicht kommerzielle Nutzung, Link auf Last.fm als Quellenangabe
Pflicht, Zwischenspeicher nach den HTTP-Kopfzeilen, hoechstens 100 MB
gespeichert. Jeder Betreiber traegt seinen eigenen Schluessel ein.

## Lidarr (API v1)

Nur lesend gemessen, an Lidarr 3.1.

- `GET /api/v1/artist`: u. a. `id`, `foreignArtistId` (MusicBrainz),
  `artistName`, `images`, `qualityProfileId`, `metadataProfileId`,
  `statistics{albumCount, trackFileCount, totalTrackCount, percentOfTracks, sizeOnDisk}`.
- ⚠️ `images[].remoteUrl` ist nicht immer eine Adresse im Netz. Bei gut der Haelfte
  der Poster stand ein lokaler Pfad darin wie `/config/MediaCover/<id>/poster.jpg`,
  `url` war `/MediaCover/<id>/poster.jpg?lastWrite=...`. Nur `http(s)` taugt
  fuer den Browser.
- `GET /api/v1/album?artistId=<id>` und `GET /api/v1/album?foreignAlbumId=<mbid>`
  (liefert eine Liste). Felder u. a. `id`, `foreignAlbumId` (Release-Group),
  `title`, `albumType`, `secondaryTypes`, `releaseDate`, `monitored`, `images`,
  `statistics{trackFileCount, totalTrackCount, percentOfTracks, sizeOnDisk}`.
  `albumType` ist z. B. `"Album"`, `secondaryTypes` eine Liste von Namen, bei
  Studioalben leer.
- Kuenstler bearbeiten: `PUT /api/v1/artist/<id>` mit dem ganzen Objekt, so wie es
  `GET /api/v1/artist` liefert (aus dem Quelltext).
- `GET /api/v1/artist/lookup?term=lidarr:<mbid>`: Kuenstler auch ausserhalb des
  Bestands, ohne `id`, mit Bildern (`poster`, `fanart`, `banner`, `clearlogo`).
  Praefixe laut Quelltext: `lidarr:`, `lidarrid:`, `mbid:`.
- `GET /api/v1/album/lookup?term=lidarr:<release-group-mbid>`: mit `remoteCover`.
- Anlegen: `POST /api/v1/artist` mit `addOptions{monitor, albumsToMonitor, monitored, searchForMissingAlbums}`.
  `AlbumMonitoredService`: Ist `albumsToMonitor` gefuellt, wird genau diese Liste
  (per `ForeignAlbumId`) ueberwacht und der Rest nicht, egal welches `monitor`.
  - ⚠️ **`monitor: none` legt den Kuenstler unueberwacht an** (`AddArtistService`),
    auch wenn `monitored: true` mitkommt. Gemessen am 12.09.2026:
    Kuenstler "Nicht ueberwacht", das Album ueberwacht, geladen wurde nichts.
    `MissingAlbumSearch` nimmt nur Alben mit `Monitored` **und** `Artist.Monitored`.
  - `monitor: unknown` mit gefuellter Liste laesst den Kuenstler ueberwacht (aus
    dem Quelltext). `unknown` ohne Liste aendert nichts, `all` ohne Liste
    ueberwacht alles.
  - Neue Alben, beim Anlegen und bei jedem Abgleich: `RefreshArtistService.ProcessChildren`
    setzt `Monitored` nach `monitorNewItems` (`none` aus, `all` an). Beim ersten
    Scan grenzt `albumsToMonitor` danach auf die Liste ein (aus dem Quelltext).
  - Die Sperre "Album umschalten geht nicht, Kuenstler nicht ueberwacht" gibt es
    nur in der Oberflaeche. `PUT /album/monitor` prueft den Kuenstler nicht
    (`AlbumService.SetMonitored`).
- Suche: `AlbumSearch` ueber `/command` prueft die Ueberwachung nicht
  (`MonitoredEpisodesOnly` wird nirgends gesetzt), die RSS-Suche schon. Ein
  unueberwachter Kuenstler bekommt ein Album also nur ueber die Sofortsuche.
- ⚠️ Faellt die Suche nach dem Anlegen aus, wiederholt Lidarr sie nicht. Gemessen am
  12.09.2026: `MissingAlbumSearch` brach mit "database is locked" ab, waehrend Lidarr
  kurz nacheinander mehrere Kuenstler anlegte und Downloads verarbeitete. Geladen wurde
  nichts, bis jemand von Hand suchte. Die Warteschlange liefert `GET /api/v1/queue`,
  je Eintrag mit `artistId` und `albumId`.
- Ganzer Kuenstler: `monitorNewItems` kennt `all`, `new` und `none`, aber keine
  Art. Welche Arten kuenftig dazukommen, bestimmt allein das Metadatenprofil.
- Metadatenprofil: `GET /api/v1/metadataprofile/<id>` mit `primaryAlbumTypes`,
  `secondaryAlbumTypes` und `releaseStatuses`, je Eintrag `{albumType{name}, allowed}`
  bzw. `{releaseStatus{name}, allowed}`. Was es ausschliesst, fehlt in den Alben des
  Kuenstlers. Am 12.09.2026 fehlte so bei einem Duo der Soundtrack.
  - ⚠️ **Jeder Kuenstler hat sein eigenes Profil** (`metadataProfileId`). Das beim
    Anlegen mitgeschickte gilt nur fuer neue Kuenstler. Gemessen am 12.09.2026: In
    nexbeat stand ein Profil mit Soundtracks, der Kuenstler hatte "Standard", und
    Lidarr fuehrte das Album weiter nicht.
  - Ein anderes Profil am Kuenstler loest kein Aktualisieren aus
    (`ArtistController.UpdateArtist` schiebt nur `MoveArtistCommand`, aus dem
    Quelltext). Neue Alben kommen erst beim naechsten Aktualisieren und werden dann
    nach `monitorNewItems` ueberwacht.
  - ⚠️ Ein weites Profil flutet grosse Diskografien. Gemessen am 12.09.2026 mit einem
    Profil, das Live, Sammlungen, Remix, Soundtrack und Bootlegs zuliess: eine Band mit
    weit ueber tausend Alben, davon keine hundert Studioalben. Waehrend des ersten
    Abgleichs, der ueber 15 Minuten lief, waren alle ueberwacht. Erst danach grenzt
    `albumsToMonitor` die Ueberwachung ein.
- Album nachtraeglich ueberwachen: `PUT /api/v1/album/monitor` mit
  `{albumIds, monitored}`. Suche: `POST /api/v1/command` mit
  `{name: "AlbumSearch", albumIds}`.
- Webhook-Ereignisse: `Test`, `Grab`, `Download`, `DownloadFailure`,
  `ImportFailure`, `Rename`, `ArtistAdd`, `ArtistDelete`, `AlbumDelete`, `Health`,
  `Retag`, `ApplicationUpdate`, `HealthRestored`. `Grab` traegt `albums[]`,
  `Download` traegt `album` mit `mbId` und `isUpgrade`.
- ⚠️ Lookups laufen ueber Lidarrs Metadatendienst (api.lidarr.audio), der
  dokumentiert ausfaellt. Finden und Empfehlen duerfen davon nicht abhaengen.

## Spotify

Faellt aus: Entwicklermodus seit 02/2026 auf 5 Testnutzer begrenzt.
