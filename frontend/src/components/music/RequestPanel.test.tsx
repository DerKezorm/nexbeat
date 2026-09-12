import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'

import { api } from '../../api/client'
import type { AlbumPageData, CreatedRequest, Me } from '../../api/types'
import { AuthContext, type AuthState } from '../../auth/AuthContext'
import i18n, { startI18n } from '../../i18n'
import { RequestPanel } from './RequestPanel'

const ALBUM = '11111111-1111-4111-8111-111111111111'

function page(overrides: Partial<AlbumPageData> = {}): AlbumPageData {
  return {
    album: {
      mbid: ALBUM,
      title: 'Record',
      primary_type: 'Album',
      secondary_types: ['Soundtrack'],
      date: '2010-12-03',
      artist_mbid: '22222222-2222-4222-8222-222222222222',
      artist_name: 'Band',
      cover: '',
      artist_image: '',
    },
    tracks: [],
    library: null,
    request: null,
    quota: { limit: null, used: 0, remaining: null, period: 'week', resets_at: '2026-09-14T00:00:00Z' },
    requests_enabled: true,
    requires_approval: false,
    dry_run: false,
    blocked: null,
    ...overrides,
  }
}

function show(data: AlbumPageData, isAdmin = false) {
  const auth: AuthState = {
    status: 'ready',
    user: { is_admin: isAdmin } as Me,
    config: null,
    needsSetup: false,
    login: vi.fn(),
    startSession: vi.fn(),
    logout: vi.fn(),
    refreshUser: vi.fn(),
    updateUser: vi.fn(),
  }
  const queries = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  return render(
    <QueryClientProvider client={queries}>
      <AuthContext.Provider value={auth}>
        <MemoryRouter>
          <RequestPanel data={data} />
        </MemoryRouter>
      </AuthContext.Provider>
    </QueryClientProvider>,
  )
}

beforeAll(async () => {
  await startI18n('de')
})

afterEach(() => {
  vi.restoreAllMocks()
})

describe('request panel', () => {
  it('says why an album cannot be requested instead of offering the button', () => {
    // 12.09.2026: Ein Soundtrack liess sich anfragen und scheiterte still am Metadatenprofil.
    show(page({ blocked: 'release_type_excluded' }))
    expect(screen.getByText(i18n.t('request.blocked'))).toBeInTheDocument()
    expect(screen.getByText(i18n.t('errors.byCode.release_type_excluded'))).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: i18n.t('request.submit') })).not.toBeInTheDocument()
  })

  it('reports a request that failed right away', async () => {
    // Eine sofort gescheiterte Anfrage zaehlt nicht, und die Seite zeigt wieder den Knopf.
    // Ohne Meldung sah das aus, als sei nichts passiert.
    const created = {
      request: { status: 'failed', error_code: 'album_not_in_lidarr' },
      quota: page().quota,
    } as unknown as CreatedRequest
    const post = vi.spyOn(api, 'post').mockResolvedValue(created)
    show(page())

    fireEvent.click(screen.getByRole('button', { name: i18n.t('request.submit') }))
    expect(await screen.findByRole('alert')).toHaveTextContent(i18n.t('errors.byCode.album_not_in_lidarr'))
    expect(post).toHaveBeenCalledWith('/api/requests', { release_group_mbid: ALBUM })
  })

  it('sends admins to Lidarr when the artist profile there is the reason', () => {
    // Das Profil aus den Einstellungen hilft bei Kuenstlern in Lidarr nicht. Der Link dorthin
    // fuehrte am 12.09.2026 in die falsche Richtung.
    show(page({ blocked: 'artist_profile_excludes_type' }), true)
    expect(screen.getByText(i18n.t('request.blockedArtistAdmin'))).toBeInTheDocument()
    expect(screen.queryByRole('link', { name: i18n.t('request.toSettings') })).not.toBeInTheDocument()
  })
})
