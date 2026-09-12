import type { DiscographyAlbum } from '../api/types'
import { withDiscographyTypes } from './albums'

function album(mbid: string, primary: string, secondary: string[] = []): DiscographyAlbum {
  return {
    mbid,
    title: mbid,
    primary_type: primary,
    secondary_types: secondary,
    date: '2024',
    listen_count: 0,
    cover: '',
    library: null,
    request: null,
  }
}

describe('popular albums with discography types', () => {
  it('take the kind from the discography once it is there', () => {
    // 12.09.2026: ListenBrainz kennt nur die Hauptart. Ein Live-Album stand dort als "Album".
    const popular = [album('a', 'Album'), album('b', 'Album')]
    const discography = [album('a', 'Album', ['Live'])]
    expect(withDiscographyTypes(popular, discography).map((item) => [item.mbid, item.primary_type, item.secondary_types])).toEqual([
      ['a', 'Album', ['Live']],
      ['b', 'Album', []],
    ])
  })

  it('leave the list alone while the discography is missing', () => {
    const popular = [album('a', 'Album')]
    expect(withDiscographyTypes(popular, [])).toEqual(popular)
  })
})
