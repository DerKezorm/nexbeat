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
    album_types: null,
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

  it('says the request is being handed over while nexcrate has not confirmed it', () => {
    // 25.09.2026: nexcrate brauchte 90 Sekunden, der Proxy meldete 504, obwohl die Anfrage ankam.
    show(page({ request: { id: 7, status: 'approved', mine: true, progress: 0, error_code: 'nexcrate_pending' } }))
    expect(screen.getByText(i18n.t('requestStatus.handing_over'))).toBeInTheDocument()
  })

  it('lets the album types be chosen when nexcrate is the target, studio albums preselected', async () => {
    // Issue #5: nexcrate kennt Arten je Kuenstler, also waehlt man sie beim Anfragen.
    const post = vi.spyOn(api, 'post').mockResolvedValue({
      request: { kind: 'artist', status: 'searching', error_code: '' },
      quota: page().quota,
    } as unknown as CreatedRequest)
    show(page({ album_types: ['studio'] }))

    fireEvent.click(screen.getByRole('button', { name: i18n.t('artistRequest.button') }))
    const dialog = screen.getByRole('dialog')
    const types = within(dialog).getByRole('group', { name: i18n.t('artistRequest.typesLabel') })
    const studio = within(types).getByRole('button', { name: i18n.t('albumTypes.studio') })
    const live = within(types).getByRole('button', { name: i18n.t('albumTypes.live') })
    expect(studio).toHaveAttribute('aria-pressed', 'true')
    expect(live).toHaveAttribute('aria-pressed', 'false')
    // Die letzte gewaehlte Art bleibt, sonst braechte die Anfrage nichts.
    expect(studio).toBeDisabled()
    expect(within(dialog).queryByText(i18n.t('artistRequest.many'))).not.toBeInTheDocument()

    fireEvent.click(live)
    expect(live).toHaveAttribute('aria-pressed', 'true')
    expect(studio).toBeEnabled()
    expect(within(dialog).getByText(i18n.t('artistRequest.many'))).toBeInTheDocument()
    fireEvent.click(within(dialog).getByRole('button', { name: i18n.t('artistRequest.confirm') }))
    await vi.waitFor(() =>
      expect(post).toHaveBeenCalledWith('/api/requests/artist', {
        artist_mbid: '22222222-2222-4222-8222-222222222222',
        types: ['studio', 'live'],
      }),
    )
  })

  it('offers no choice and sends no types when Lidarr is the target', async () => {
    const post = vi.spyOn(api, 'post').mockResolvedValue({
      request: { kind: 'artist', status: 'searching', error_code: '' },
      quota: page().quota,
    } as unknown as CreatedRequest)
    show(page())

    fireEvent.click(screen.getByRole('button', { name: i18n.t('artistRequest.button') }))
    const dialog = screen.getByRole('dialog')
    expect(within(dialog).queryByRole('group')).not.toBeInTheDocument()
    fireEvent.click(within(dialog).getByRole('button', { name: i18n.t('artistRequest.confirm') }))
    await vi.waitFor(() =>
      expect(post).toHaveBeenCalledWith('/api/requests/artist', { artist_mbid: '22222222-2222-4222-8222-222222222222' }),
    )
  })

  it('names the requested types next to the status', () => {
    show(
      page({
        album_types: ['studio'],
        request: { id: 7, status: 'searching', mine: true, progress: 0, error_code: '', album_types: ['studio', 'compilation'] },
      }),
    )
    expect(screen.getByText(`${i18n.t('albumTypes.studio')}, ${i18n.t('albumTypes.compilation')}`)).toBeInTheDocument()
  })

  it('says why a whole artist cannot be requested instead of offering the button', () => {
    // 12.09.2026: Mit einem weiten Metadatenprofil brachte "Ganzer Kuenstler" weit ueber tausend Alben nach Lidarr.
    show(page({ blocked: 'profile_not_studio_only' }))
    expect(screen.queryByRole('button', { name: i18n.t('artistRequest.button') })).not.toBeInTheDocument()
    expect(screen.getByText(i18n.t('errors.byCode.profile_not_studio_only'))).toBeInTheDocument()
  })
})
