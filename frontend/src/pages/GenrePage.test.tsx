import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'

import { ApiError, api } from '../api/client'
import type { GenreAlbums, GenreArtists } from '../api/types'
import i18n, { startI18n } from '../i18n'
import { GenrePage } from './GenrePage'

const ARTISTS: GenreArtists = {
  artists: [{ mbid: 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa', name: 'Jazz Star', image: '', in_library: true }],
  related: ['vocal jazz'],
  ranked: false,
}
const NO_ALBUMS: GenreAlbums = { available: true, albums: [] }
const ARTISTS_PATH = '/api/genres/artists?tag=jazz'
const ALBUMS_PATH = '/api/genres/albums?tag=jazz'

function show(answer: (path: string) => Promise<unknown>) {
  // Von Hand mitgeschrieben: Ein Spy haengt an abgelehnte Antworten selbst einen Handler.
  const asked: string[] = []
  vi.spyOn(api, 'get').mockImplementation((async (path: string) => {
    asked.push(path)
    return answer(path)
  }) as typeof api.get)
  const queries = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(
    <QueryClientProvider client={queries}>
      <MemoryRouter initialEntries={['/genre/jazz']}>
        <Routes>
          <Route path="/genre/:tag" element={<GenrePage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
  return { asked, queries }
}

async function pause() {
  await act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 50))
  })
}

beforeAll(async () => {
  await startI18n('de')
})

afterEach(() => {
  vi.restoreAllMocks()
})

describe('genre page', () => {
  it('asks for the albums only once the artists are there', async () => {
    let release: (value: GenreArtists) => void = () => {}
    const { asked } = show((path) =>
      path === ARTISTS_PATH ? new Promise<GenreArtists>((resolve) => (release = resolve)) : Promise.resolve(NO_ALBUMS),
    )
    await pause()
    expect(asked).toEqual([ARTISTS_PATH])

    release(ARTISTS)
    expect(await screen.findByText('Jazz Star')).toBeInTheDocument()
    await waitFor(() => expect(asked).toEqual([ARTISTS_PATH, ALBUMS_PATH]))
  })

  it('leaves out the albums when ListenBrainz wants a key, as on the artist page', async () => {
    // 12.09.2026: Beim Schlager gab ListenBrainz ohne Schluessel fuer keinen der acht Spitzenkuenstler
    // die Alben heraus. "Erneut versuchen" haette daran nichts geaendert.
    const { asked, queries } = show(async (path) => {
      if (path === ARTISTS_PATH) return ARTISTS
      throw new ApiError(503, i18n.t('errors.byCode.listenbrainz_token_required'), 'listenbrainz_token_required')
    })
    expect(await screen.findByText('Jazz Star')).toBeInTheDocument()
    await waitFor(() => expect(queries.getQueryState(['genre', 'jazz', 'albums'])?.status).toBe('error'))
    await pause()
    expect(asked).toContain(ALBUMS_PATH)
    expect(screen.queryByText(i18n.t('genre.albums'))).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: i18n.t('common.tryAgain') })).not.toBeInTheDocument()
  })

  it('offers a new try when ListenBrainz does not answer', async () => {
    show(async (path) => {
      if (path === ARTISTS_PATH) return ARTISTS
      throw new ApiError(503, i18n.t('errors.byCode.listenbrainz_unavailable'), 'listenbrainz_unavailable')
    })
    expect(await screen.findByRole('button', { name: i18n.t('common.tryAgain') })).toBeInTheDocument()
    expect(screen.getByText(i18n.t('genre.albums'))).toBeInTheDocument()
  })

  it('says when the order is not by listens and links related genres by their name', async () => {
    show(async (path) => (path === ARTISTS_PATH ? ARTISTS : NO_ALBUMS))
    expect(await screen.findByText(i18n.t('genre.unranked'))).toBeInTheDocument()
    expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent('Jazz.')
    expect(screen.getByRole('link', { name: 'Vocal Jazz' })).toHaveAttribute('href', '/genre/vocal%20jazz')
  })
})
