/**
 * Die Hauptgenres der Entdecken-Seite.
 *
 * `tag` ist der Name bei MusicBrainz, klein geschrieben, so sucht die Tag-Suche. `key`
 * fuehrt zum uebersetzten Namen unter `genre.names`. Gewaehlt am 12.09.2026 nach einer
 * Messung: Diese Genres trugen die meistgehoerten Kuenstler bei ListenBrainz am haeufigsten,
 * und die Tag-Suche fand dazu bekannte Namen.
 */
export const MAIN_GENRES = [
  { tag: 'rock', key: 'rock' },
  { tag: 'pop', key: 'pop' },
  { tag: 'hip hop', key: 'hipHop' },
  { tag: 'electronic', key: 'electronic' },
  { tag: 'r&b', key: 'rnb' },
  { tag: 'alternative rock', key: 'alternative' },
  { tag: 'indie rock', key: 'indie' },
  { tag: 'metal', key: 'metal' },
  { tag: 'punk', key: 'punk' },
  { tag: 'jazz', key: 'jazz' },
  { tag: 'soul', key: 'soul' },
  { tag: 'funk', key: 'funk' },
  { tag: 'folk', key: 'folk' },
  { tag: 'country', key: 'country' },
  { tag: 'blues', key: 'blues' },
  { tag: 'classical', key: 'classical' },
  { tag: 'reggae', key: 'reggae' },
  { tag: 'latin', key: 'latin' },
  { tag: 'k-pop', key: 'kpop' },
  { tag: 'schlager', key: 'schlager' },
] as const satisfies readonly { tag: string; key: string }[]

/** Klein bleiben, ausser am Anfang: "Drum and Bass", nicht "Drum And Bass". */
const SMALL_WORDS = new Set(['and', 'n', 'of', 'the'])

export function genrePath(tag: string): string {
  return `/genre/${encodeURIComponent(tag)}`
}

/** Hauptgenres uebersetzt. Alle anderen so, wie MusicBrainz sie nennt, mit grossen Anfangsbuchstaben. */
export function genreName(tag: string, t: (key: string) => string): string {
  const main = MAIN_GENRES.find((genre) => genre.tag === tag)
  if (main) return t(`genre.names.${main.key}`)
  return tag
    .split(' ')
    .map((word, index) =>
      index > 0 && SMALL_WORDS.has(word)
        ? word
        : word
            .split('-')
            .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
            .join('-'),
    )
    .join(' ')
}
