import type { DiscographyAlbum } from '../api/types'

/**
 * "Am meisten gehoert" mit den Arten aus der Diskografie. ListenBrainz kennt nur die
 * Hauptart, ein Live-Album stand dort als "Album". Solange die Diskografie fehlt, bleibt
 * die Liste, wie sie ist.
 */
export function withDiscographyTypes(popular: DiscographyAlbum[], discography: DiscographyAlbum[]): DiscographyAlbum[] {
  if (discography.length === 0) return popular
  const known = new Map(discography.map((album) => [album.mbid, album]))
  return popular.map((album) => {
    const match = known.get(album.mbid)
    return match ? { ...album, primary_type: match.primary_type, secondary_types: match.secondary_types } : album
  })
}
