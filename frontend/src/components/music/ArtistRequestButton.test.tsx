import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, within } from '@testing-library/react'

import { api } from '../../api/client'
import type { ArtistPageData, CreatedRequest, Me } from '../../api/types'
import { AuthContext, type AuthState } from '../../auth/AuthContext'
import i18n, { startI18n } from '../../i18n'
import { ArtistRequestButton } from './ArtistRequestButton'

function page(overrides: Partial<ArtistPageData> = {}): ArtistPageData {
  return {
    artist: {
      mbid: '22222222-2222-4222-8222-222222222222',
      name: 'Band',
      type: 'Group',
      country: '',
      disambiguation: '',
      begin: '',
      end: '',
      tags: [],
      image: '',
      in_library: true,
      track_file_count: 0,
    },
    sources: { listenbrainz: true, deezer: true },
    request: null,
    requests_enabled: true,
    requires_approval: false,
    dry_run: false,
    blocked: null,
    quota: { limit: null, used: 0, remaining: null, period: 'week', resets_at: '2026-09-14T00:00:00Z' },
    ...overrides,
  }
}

const auth: AuthState = {
  status: 'ready',
  user: { is_admin: false } as Me,
  config: null,
  needsSetup: false,
  login: vi.fn(),
  startSession: vi.fn(),
  logout: vi.fn(),
  refreshUser: vi.fn(),
  updateUser: vi.fn(),
}

function show(data: ArtistPageData) {
  const queries = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  return render(
    <QueryClientProvider client={queries}>
      <AuthContext.Provider value={auth}>
        <ArtistRequestButton data={data} />
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

describe('whole artist request', () => {
  it('keeps the dialog open and says why when the request failed right away', async () => {
    // Wie bei Alben: Eine sofort gescheiterte Anfrage zaehlt nicht, und der Knopf steht
    // wieder da. Ohne Meldung sah das aus, als sei nichts passiert.
    const created = {
      request: { kind: 'artist', status: 'failed', error_code: 'artist_albums_not_in_lidarr' },
      quota: page().quota,
    } as unknown as CreatedRequest
    vi.spyOn(api, 'post').mockResolvedValue(created)
    show(page())

    fireEvent.click(screen.getByRole('button', { name: i18n.t('artistRequest.button') }))
    const dialog = screen.getByRole('dialog')
    fireEvent.click(within(dialog).getByRole('button', { name: i18n.t('artistRequest.confirm') }))
    expect(await within(dialog).findByRole('alert')).toHaveTextContent(i18n.t('errors.byCode.artist_albums_not_in_lidarr'))
    expect(screen.getByRole('dialog')).toBeInTheDocument()
  })

  it('says why a whole artist cannot be requested instead of offering the button', () => {
    // 12.09.2026: Mit einem weiten Metadatenprofil brachte "Ganzer Kuenstler" weit ueber tausend Alben nach Lidarr.
    show(page({ blocked: 'profile_not_studio_only' }))
    expect(screen.queryByRole('button', { name: i18n.t('artistRequest.button') })).not.toBeInTheDocument()
    expect(screen.getByText(i18n.t('errors.byCode.profile_not_studio_only'))).toBeInTheDocument()
  })
})
