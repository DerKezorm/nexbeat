import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'

import { api } from '../../api/client'
import type { AppConfig } from '../../api/types'
import { AuthContext, type AuthState } from '../../auth/AuthContext'
import i18n, { startI18n } from '../../i18n'
import { LoginPage } from '../LoginPage'
import { AdminSigninSettings } from '../settings/AdminSigninSettings'
import { ProviderLinksSection } from './ProviderLinksSection'

function wrap(children: React.ReactNode, path = '/') {
  const queries = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  return render(
    <QueryClientProvider client={queries}>
      <MemoryRouter initialEntries={[path]}>{children}</MemoryRouter>
    </QueryClientProvider>,
  )
}

const CONFIG: AppConfig = {
  version: '1.3.0',
  needs_setup: false,
  mail_configured: false,
  default_language: 'de',
  previews_enabled: false,
  requests_enabled: true,
  oidc_providers: [{ slug: 'entra', label: 'Microsoft' }],
}

function auth(config: AppConfig): AuthState {
  const nothing = async () => undefined
  return {
    status: 'ready',
    user: null,
    config,
    needsSetup: false,
    login: nothing,
    startSession: nothing,
    logout: nothing,
    refreshUser: nothing,
    updateUser: () => undefined,
  }
}

beforeAll(async () => {
  await startI18n('de')
})

afterEach(() => {
  vi.restoreAllMocks()
})

describe('sign-in providers', () => {
  it('appear on the sign-in page as plain links into the provider', () => {
    wrap(
      <AuthContext.Provider value={auth(CONFIG)}>
        <LoginPage />
      </AuthContext.Provider>,
    )
    const link = screen.getByRole('link', { name: i18n.t('login.oidcWith', { label: 'Microsoft' }) })
    expect(link).toHaveAttribute('href', '/api/auth/oidc/entra/login')
  })

  it('leave the sign-in page alone when there are none', () => {
    wrap(
      <AuthContext.Provider value={auth({ ...CONFIG, oidc_providers: [] })}>
        <LoginPage />
      </AuthContext.Provider>,
    )
    expect(screen.queryByText(i18n.t('login.oidcOr'))).not.toBeInTheDocument()
  })

  it('name a failed return from the provider in words, not as a code', () => {
    wrap(
      <AuthContext.Provider value={auth(CONFIG)}>
        <LoginPage />
      </AuthContext.Provider>,
      '/login?oidc_error=oidc_email_taken',
    )
    expect(screen.getByText(i18n.t('errors.byCode.oidc_email_taken'))).toBeInTheDocument()
  })

  it('are linked from the profile through the address the server hands out', async () => {
    vi.spyOn(api, 'get').mockResolvedValue([{ slug: 'entra', label: 'Microsoft', linked: false }])
    const post = vi.spyOn(api, 'post').mockResolvedValue({ url: 'https://login.example.com/authorize?x=1' })
    const assign = vi.fn()
    vi.spyOn(window, 'location', 'get').mockReturnValue({ ...window.location, assign })
    wrap(<ProviderLinksSection />)

    fireEvent.click(await screen.findByRole('button', { name: i18n.t('profile.providerLink') }))
    await waitFor(() => expect(assign).toHaveBeenCalledWith('https://login.example.com/authorize?x=1'))
    expect(post).toHaveBeenCalledWith('/api/oidc/links/entra')
  })

  it('report a finished link once and clear it from the address', async () => {
    vi.spyOn(api, 'get').mockResolvedValue([{ slug: 'entra', label: 'Microsoft', linked: true }])
    wrap(<ProviderLinksSection />, '/profil?oidc_linked=entra')
    expect(await screen.findByText(i18n.t('profile.providerLinkedOk', { label: 'Microsoft' }))).toBeInTheDocument()
    expect(screen.getByRole('button', { name: i18n.t('profile.providerUnlink') })).toBeInTheDocument()
  })

  it('are set up in authentik with a token that does not stay in the page', async () => {
    vi.spyOn(api, 'get').mockImplementation((async (path: string) =>
      path === '/api/settings' ? { public_url: 'https://music.example.com' } : []) as typeof api.get)
    const post = vi.spyOn(api, 'post').mockResolvedValue({
      ok: true,
      steps: [{ key: 'reached', ok: true, detail: 'authentik 2026.8.1' }],
    })
    wrap(<AdminSigninSettings />)

    const token = await screen.findByLabelText(i18n.t('signin.authentikToken'))
    fireEvent.change(screen.getByLabelText(i18n.t('signin.authentikUrl')), { target: { value: 'https://auth.example.com' } })
    fireEvent.change(token, { target: { value: 'one-time-token' } })
    fireEvent.click(screen.getByRole('button', { name: i18n.t('signin.authentikRun') }))

    expect(await screen.findByText(i18n.t('signin.authentikDone'))).toBeInTheDocument()
    expect(post).toHaveBeenCalledWith('/api/oidc/authentik/setup', { url: 'https://auth.example.com', token: 'one-time-token' })
    expect(token).toHaveValue('')
    // Die Rueckleitadresse fuer Entra und Co. steht unter dem Formular.
    expect(screen.getByText(/https:\/\/music\.example\.com\/api\/auth\/oidc\/…\/callback/)).toBeInTheDocument()
  })
})
