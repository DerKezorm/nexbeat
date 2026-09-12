import i18n, { startI18n } from '../i18n'
import { genreName, genrePath } from './genres'

beforeAll(async () => {
  await startI18n('de')
})

describe('genre names', () => {
  it('translates the main genres and capitalises the others', () => {
    const t = (key: string) => i18n.t(key)
    expect(genreName('hip hop', t)).toBe('Hip-Hop')
    expect(genreName('classical', t)).toBe('Klassik')
    expect(genreName('drum and bass', t)).toBe('Drum and Bass')
    expect(genreName('post-punk', t)).toBe('Post-Punk')
    expect(genreName('east coast hip hop', t)).toBe('East Coast Hip Hop')
  })

  it('keeps special characters in the address', () => {
    expect(genrePath('r&b')).toBe('/genre/r%26b')
    expect(genrePath('hip hop')).toBe('/genre/hip%20hop')
  })
})
