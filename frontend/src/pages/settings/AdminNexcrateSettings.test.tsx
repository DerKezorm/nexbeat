import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, renderHook, screen } from '@testing-library/react'
import type { ReactNode } from 'react'

import { api } from '../../api/client'
import type { AppSettings, Me, NexcrateStatus } from '../../api/types'
import { AuthContext, type AuthState } from '../../auth/AuthContext'
import i18n, { startI18n } from '../../i18n'
import { useTarget } from '../../lib/target'
import { AdminNexcrateSettings } from './AdminNexcrateSettings'
import { AdminServicesSettings } from './AdminServicesSettings'

const SETTINGS = {
  request_mode: 'nex',
  nexcrate_url: '',
  nexcrate_api_key: '',
  nexcrate_api_key_set: false,
  lidarr_url: '',
  lidarr_api_key: '',
  lidarr_api_key_set: false,
  lidarr_dry_run: false,
} as unknown as AppSettings

const OFF: NexcrateStatus = {
  url: '',
  connected: false,
  key_hint: null,
  events: { connected: false, since: null, last_event_at: null, last_seq: null, error: null },
  artists: 0,
  facts: null,
  error: null,
}

const ON: NexcrateStatus = {
  ...OFF,
  url: 'http://nexcrate.example.com:8390',
  connected: true,
  key_hint: 'BaWQ',
  artists: 2,
  facts: {
    ok: true,
    version: '0.1.0',
    contract: 1,
    stage: 'V5',
    music: true,
    scopes: ['read', 'request'],
    can_request: true,
    music_versions: [{ name: 'Music', tier: null, ready: false, reasons: ['no_indexer', 'automatic_off'] }],
  },
}

function auth(overrides: Partial<AuthState> = {}): AuthState {
  return {
    status: 'ready',
    user: { is_admin: true, request_target: 'nexcrate' } as Me,
    config: null,
    needsSetup: false,
    login: vi.fn(),
    startSession: vi.fn(),
    logout: vi.fn(),
    refreshUser: vi.fn(async () => undefined),
    updateUser: vi.fn(),
    ...overrides,
  }
}

function show(node: ReactNode, value: AuthState = auth()) {
  const queries = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  return render(
    <QueryClientProvider client={queries}>
      <AuthContext.Provider value={value}>{node}</AuthContext.Provider>
    </QueryClientProvider>,
  )
}

function answer(answers: Record<string, unknown>) {
  return vi.spyOn(api, 'get').mockImplementation((async (path: string) => {
    if (!(path in answers)) throw new Error(`unexpected ${path}`)
    return answers[path]
  }) as typeof api.get)
}

beforeAll(async () => {
  await startI18n('de')
})

afterEach(() => {
  vi.restoreAllMocks()
})

describe('nexcrate settings', () => {
  it('pair with a code the owner confirms in nexcrate', async () => {
    const answers: Record<string, unknown> = {
      '/api/settings': SETTINGS,
      '/api/settings/nexcrate/status': OFF,
      '/api/settings/nexcrate/pairing': { state: 'none' },
    }
    answer(answers)
    const post = vi.spyOn(api, 'post').mockResolvedValue({
      state: 'pending',
      code: '5Z3-M4G',
      url: 'http://nexcrate.example.com:8390',
      expires_at: new Date(Date.now() + 600_000).toISOString(),
      poll_seconds: 0.05,
    })
    const value = auth()
    show(<AdminNexcrateSettings />, value)

    fireEvent.change(await screen.findByLabelText(i18n.t('nexcrate.url')), {
      target: { value: ' http://nexcrate.example.com:8390 ' },
    })
    fireEvent.click(screen.getByRole('button', { name: i18n.t('nexcrate.pair') }))
    expect(await screen.findByText('5Z3-M4G')).toBeInTheDocument()
    expect(post).toHaveBeenCalledWith('/api/settings/nexcrate/pairing', { url: 'http://nexcrate.example.com:8390' })

    answers['/api/settings/nexcrate/status'] = ON
    answers['/api/settings/nexcrate/pairing'] = { state: 'confirmed', scopes: ['read', 'request'] }
    expect(await screen.findByText('nexcrate 0.1.0', {}, { timeout: 3000 })).toBeInTheDocument()
    expect(value.refreshUser).toHaveBeenCalled()
  })

  it('say that a denied pairing made no key', async () => {
    answer({
      '/api/settings': SETTINGS,
      '/api/settings/nexcrate/status': OFF,
      '/api/settings/nexcrate/pairing': { state: 'denied' },
    })
    show(<AdminNexcrateSettings />)
    expect(await screen.findByRole('alert')).toHaveTextContent(i18n.t('nexcrate.pairingDenied'))
    expect(screen.getByRole('button', { name: i18n.t('nexcrate.again') })).toBeInTheDocument()
  })

  it('name what the music version lacks, but not a switched off automatic', async () => {
    // Die Automatik aus haelt eine Anfrage nicht auf: nexcrate sucht einen Suchwunsch trotzdem.
    answer({
      '/api/settings': { ...SETTINGS, nexcrate_url: ON.url, nexcrate_api_key_set: true },
      '/api/settings/nexcrate/status': ON,
      '/api/settings/nexcrate/pairing': { state: 'none' },
    })
    show(<AdminNexcrateSettings />)
    expect(await screen.findByText(i18n.t('nexcrate.notReadyTitle'))).toBeInTheDocument()
    const reasons = screen.getAllByRole('listitem').map((item) => item.textContent)
    expect(reasons).toEqual([i18n.t('nexcrate.reason.no_indexer')])
    expect(screen.getByText(i18n.t('nexcrate.automaticOff'))).toBeInTheDocument()
  })

  it('send the key typed by hand and check it', async () => {
    answer({
      '/api/settings': SETTINGS,
      '/api/settings/nexcrate/status': OFF,
      '/api/settings/nexcrate/pairing': { state: 'none' },
    })
    const put = vi.spyOn(api, 'put').mockResolvedValue(SETTINGS)
    const post = vi.spyOn(api, 'post').mockResolvedValue(ON.facts)
    show(<AdminNexcrateSettings />)
    fireEvent.change(await screen.findByLabelText(i18n.t('nexcrate.url')), { target: { value: 'http://nexcrate.example.com:8390' } })
    fireEvent.click(screen.getByRole('button', { name: i18n.t('nexcrate.manual') }))
    fireEvent.change(screen.getByLabelText(i18n.t('nexcrate.apiKey')), { target: { value: 'nxc_example' } })
    fireEvent.click(screen.getByRole('button', { name: i18n.t('nexcrate.saveAndCheck') }))
    await vi.waitFor(() => expect(post).toHaveBeenCalledWith('/api/settings/test/nexcrate', {}))
    expect(put).toHaveBeenCalledWith('/api/settings', { nexcrate_url: 'http://nexcrate.example.com:8390', nexcrate_api_key: 'nxc_example' })
  })
})

describe('services', () => {
  it('keep an installation with Lidarr in arr mode and switch it to nex on a click', async () => {
    const lidarrOnly = { ...SETTINGS, request_mode: '', lidarr_url: 'http://lidarr.example.com:8686', lidarr_api_key_set: true }
    const answers: Record<string, unknown> = {
      '/api/settings': lidarrOnly,
      '/api/settings/lidarr/options': { quality_profiles: [], metadata_profiles: [], root_folders: [] },
      '/api/settings/webhook': { path: '/api/webhooks/lidarr', username: 'nexbeat', password: 'x', events: [] },
      '/api/settings/nexcrate/status': OFF,
      '/api/settings/nexcrate/pairing': { state: 'none' },
    }
    answer(answers)
    const put = vi.spyOn(api, 'put').mockImplementation((async () => {
      answers['/api/settings'] = { ...lidarrOnly, request_mode: 'nex' }
      return answers['/api/settings']
    }) as typeof api.put)
    const value = auth({ user: { is_admin: true, request_target: 'lidarr' } as Me })
    show(<AdminServicesSettings />, value)

    const arr = await screen.findByRole('radio', { name: new RegExp(i18n.t('services.arr')) })
    expect(arr).toHaveAttribute('aria-checked', 'true')
    fireEvent.click(screen.getByRole('radio', { name: new RegExp(i18n.t('services.nex')) }))
    await vi.waitFor(() => expect(put).toHaveBeenCalledWith('/api/settings', { request_mode: 'nex' }))
    expect(await screen.findByText(i18n.t('services.switchNote'))).toBeInTheDocument()
    expect(value.refreshUser).toHaveBeenCalled()
    expect(await screen.findByText(i18n.t('nexcrate.promise'))).toBeInTheDocument()
  })
})

describe('target name', () => {
  it.each([
    ['nexcrate', 'nexcrate'],
    ['lidarr', 'Lidarr'],
    [null, 'Lidarr oder nexcrate'],
  ])('for %s is %s', (target, expected) => {
    const value = auth({ user: { is_admin: false, request_target: target } as Me })
    const { result } = renderHook(() => useTarget(), {
      wrapper: ({ children }) => <AuthContext.Provider value={value}>{children}</AuthContext.Provider>,
    })
    expect(result.current).toBe(expected)
    expect(i18n.t('request.searching', { target: result.current })).toBe(`${expected} sucht`)
  })
})
