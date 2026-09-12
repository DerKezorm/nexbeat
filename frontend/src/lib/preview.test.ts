import { albumPreview, artistPreview } from './preview'

describe('link previews', () => {
  it('read what a card passes along', () => {
    expect(albumPreview({ album: { title: 'Record', cover: '/c.jpg', artist: 'Band' } })).toEqual({
      title: 'Record',
      cover: '/c.jpg',
      artist: 'Band',
    })
    expect(artistPreview({ artist: { name: 'Band', image: '/i.jpg' } })).toEqual({ name: 'Band', image: '/i.jpg' })
  })

  it('ignore anything else', () => {
    expect(albumPreview(null)).toBeNull()
    expect(albumPreview({ album: { title: 42 } })).toBeNull()
    expect(artistPreview('Band')).toBeNull()
    expect(artistPreview({ artist: { image: '/i.jpg' } })).toBeNull()
  })
})
