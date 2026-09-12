import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen } from '@testing-library/react'

import { api } from '../../api/client'
import type { AppSettings, LidarrOptions, WebhookInfo } from '../../api/types'
import i18n, { startI18n } from '../../i18n'
import { AdminLidarrSettings } from './AdminLidarrSettings'

const SETTINGS = {
  lidarr_url: 'http://lidarr.example.com:8686',
  lidarr_api_key: '••••abcd',
  lidarr_api_key_set: true,
  lidarr_root_folder: '/music',
  lidarr_quality_profile_id: 1,
  lidarr_metadata_profile_id: 3,
  lidarr_dry_run: false,
  public_url: 'https://nexbeat.example.com',
} as unknown as AppSettings

const OPTIONS = {
  quality_profiles: [{ id: 1, name: 'Lossless' }],
  metadata_profiles: [
    { id: 1, name: 'Standard', primary: ['Album'], secondary: ['Studio'], statuses: ['Official'], studio_only: true },
    {
      id: 3,
      name: 'Wide',
      primary: ['Album', 'EP'],
      secondary: ['Studio', 'Live', 'Compilation'],
      statuses: ['Official', 'Bootleg'],
      studio_only: false,
    },
  ],
  root_folders: [{ path: '/music', free_space: 1, accessible: true }],
} as unknown as LidarrOptions

const WEBHOOK: WebhookInfo = { path: '/api/webhooks/lidarr', username: 'nexbeat', password: 'secret', events: ['On Grab'] }

beforeAll(async () => {
  await startI18n('de')
})

afterEach(() => {
  vi.restoreAllMocks()
})

describe('lidarr settings', () => {
  it('show what a metadata profile allows and warn when it is more than studio albums', async () => {
    // 12.09.2026: Ein Profil, dessen Name nur Soundtracks und Remixe nannte, liess auch Live, Sammlungen
    // und Bootlegs zu. "Ganzer Kuenstler" brachte damit eine Band mit weit ueber tausend Alben nach Lidarr.
    const answers: Record<string, unknown> = {
      '/api/settings': SETTINGS,
      '/api/settings/lidarr/options': OPTIONS,
      '/api/settings/webhook': WEBHOOK,
    }
    vi.spyOn(api, 'get').mockImplementation((async (path: string) => {
      if (!(path in answers)) throw new Error(`unexpected ${path}`)
      return answers[path]
    }) as typeof api.get)
    const queries = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    render(
      <QueryClientProvider client={queries}>
        <AdminLidarrSettings />
      </QueryClientProvider>,
    )

    expect(await screen.findByText(i18n.t('lidarr.profileWide'))).toBeInTheDocument()
    expect(screen.getByText(/Studio, Live, Compilation/)).toBeInTheDocument()

    fireEvent.change(screen.getByRole('combobox', { name: new RegExp(i18n.t('lidarr.metadataProfile')) }), {
      target: { value: '1' },
    })
    expect(screen.queryByText(i18n.t('lidarr.profileWide'))).not.toBeInTheDocument()
  })
})
