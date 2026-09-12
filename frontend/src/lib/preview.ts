/**
 * Was eine Karte beim Klick schon weiss. Die naechste Seite zeigt es sofort,
 * waehrend der Rest laedt: MusicBrainz braucht zur Spitzenzeit Sekunden.
 */

export type AlbumPreview = { title: string; cover: string; artist: string }
export type ArtistPreview = { name: string; image: string }

function field(value: unknown, key: string): unknown {
  return value !== null && typeof value === 'object' ? (value as Record<string, unknown>)[key] : undefined
}

function text(value: unknown): string {
  return typeof value === 'string' ? value : ''
}

export function albumPreview(state: unknown): AlbumPreview | null {
  const album = field(state, 'album')
  const title = text(field(album, 'title'))
  return title ? { title, cover: text(field(album, 'cover')), artist: text(field(album, 'artist')) } : null
}

export function artistPreview(state: unknown): ArtistPreview | null {
  const artist = field(state, 'artist')
  const name = text(field(artist, 'name'))
  return name ? { name, image: text(field(artist, 'image')) } : null
}
