/**
 * Die Anmeldung ueber Anbieter in der Oberflaeche: Anmeldeseite,
 * Einladungsseite, die drei Karten unter Einstellungen, Mein Konto. Der Server ist hier durch Attrappen von `api`
 * ersetzt; den ganzen Weg gehen die Ende-zu-Ende-Tests in `e2e/nexoidc.spec.ts`.
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import type { ReactNode } from 'react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'

import { ApiError, api } from '../api/client'
import type { AppConfig, AppSettings, OidcProvider } from '../api/types'
import { AuthContext, type AuthState } from '../auth/AuthContext'
import { startI18n } from '../i18n'
import { LoginPage } from './LoginPage'
import { InvitationPage } from './OnboardingPage'
import { ProviderLinksSection } from './profile/ProviderLinksSection'
import { SignInCards } from './settings/SignInCards'

const CONFIG: AppConfig = {
  version: '1.3.0',
  needs_setup: false,
  mail_configured: false,
  default_language: 'de',
  previews_enabled: false,
  requests_enabled: true,
  oidc_providers: [
    { slug: 'entra', label: 'Microsoft' },
    { slug: 'authentik', label: 'authentik' },
  ],
  password_login: true,
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

function wrap(children: ReactNode, path = '/', config: AppConfig = CONFIG, route = '*') {
  const queries = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  return render(
    <QueryClientProvider client={queries}>
      <AuthContext.Provider value={auth(config)}>
        <MemoryRouter initialEntries={[path]}>
          <Routes>
            <Route path={route} element={children} />
          </Routes>
        </MemoryRouter>
      </AuthContext.Provider>
    </QueryClientProvider>,
  )
}

const SETTINGS = { public_url: 'https://music.example.com', password_login: true } as AppSettings

function provider(change: Partial<OidcProvider> = {}): OidcProvider {
  return {
    id: 1,
    slug: 'authentik',
    label: 'authentik',
    issuer: 'https://auth.example.com/application/o/nexbeat',
    client_id: 'abc',
    has_secret: true,
    scopes: 'openid profile email',
    enabled: true,
    auto_create: false,
    trusts_second_factor: true,
    managed: 'authentik',
    position: 0,
    redirect_uri: 'https://music.example.com/api/auth/oidc/authentik/callback',
    registered_redirect_uri: '',
    redirect_stale: false,
    links: 2,
    editable: true,
    ...change,
  }
}

const ADDRESS = {
  public_url: 'https://music.example.com',
  seen: 'https://music.example.com',
  forwarded_proto: '',
  forwarded_host: '',
  proxy_ignored: false,
  callback_path: '/api/auth/oidc/authentik/callback',
  redirect_uri: 'https://music.example.com/api/auth/oidc/authentik/callback',
  registered_redirect_uri: '',
  stale: false,
}

function serve(answers: Record<string, unknown>) {
  return vi.spyOn(api, 'get').mockImplementation(async (path: string) => {
    const key = Object.keys(answers).find((prefix) => path.startsWith(prefix))
    if (!key) throw new Error(`unexpected GET ${path}`)
    return answers[key] as never
  })
}

beforeAll(async () => {
  await startI18n('de')
})

afterEach(() => {
  vi.restoreAllMocks()
})

describe('the sign-in page', () => {
  it('has one button per provider in the order of the list, below "oder"', () => {
    wrap(<LoginPage />, '/login')
    const buttons = screen.getAllByRole('button', { name: /^Mit .* anmelden$/ })
    expect(buttons.map((button) => button.textContent)).toEqual(['Mit Microsoft anmelden', 'Mit authentik anmelden'])
    expect(buttons[0]).toHaveAttribute('href', '/api/oidc/entra/start')
    expect(screen.getByText('oder')).toBeInTheDocument()
    expect(screen.getByLabelText('Passwort')).toBeInTheDocument()
  })

  it('names a refused return in words and never shows a raw code from the address', () => {
    const { unmount } = wrap(<LoginPage />, '/login?error=oidc_no_account')
    expect(screen.getByRole('alert')).toHaveTextContent('Für dich gibt es hier kein Konto.')
    unmount()
    wrap(<LoginPage />, '/login?error=%3Cb%3Eboom%3C%2Fb%3E')
    expect(screen.queryByRole('alert')).toBeNull()
  })

  it('shows only the buttons while password sign-in is off, and the operator still gets the form', () => {
    wrap(<LoginPage />, '/login', { ...CONFIG, password_login: false })
    expect(screen.queryByLabelText('Passwort')).toBeNull()
    expect(screen.getAllByRole('button', { name: /^Mit .* anmelden$/ })).toHaveLength(2)
    fireEvent.click(screen.getByRole('button', { name: 'Als Betreiber mit Passwort anmelden' }))
    expect(screen.getByLabelText('Passwort')).toBeInTheDocument()
  })
})

describe('the invitation page', () => {
  it('offers to continue with each provider and takes the invitation along', async () => {
    serve({ '/api/onboarding/invitation/': { email: 'kim@example.com', role: 'user' } })
    wrap(<InvitationPage />, '/einladung/key-1', CONFIG, '/einladung/:token')
    const button = await screen.findByRole('button', { name: 'Weiter mit Microsoft' })
    expect(button).toHaveAttribute('href', '/api/oidc/entra/start?invite=key-1')
  })
})

describe('settings, sign-in', () => {
  it('shows the three cards, the marks of an entry, and locks the password switch without an active provider', async () => {
    serve({ '/api/settings': SETTINGS, '/api/oidc/admin/providers': [provider({ enabled: false })], '/api/oidc/authentik/address': ADDRESS })
    wrap(<SignInCards />)
    for (const title of ['Anmeldung', 'Anmeldeanbieter', 'authentik in einem Schritt']) {
      expect(await screen.findByRole('heading', { name: title })).toBeInTheDocument()
    }
    const row = within(screen.getByTestId('provider-list')).getByRole('listitem')
    expect(row).toHaveTextContent('aus')
    expect(row).toHaveTextContent('über authentik eingerichtet')
    expect(screen.getByLabelText(/^Anmeldung mit Passwort/)).toBeDisabled()
  })

  it('opens the form as a dialog with the fields in the order of the blueprint, the slug from the name', async () => {
    serve({ '/api/settings': SETTINGS, '/api/oidc/admin/providers': [], '/api/oidc/authentik/address': ADDRESS })
    wrap(<SignInCards />)
    expect(await screen.findByText(/Noch kein Anbieter\./)).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Anbieter hinzufügen' }))
    const form = screen.getByTestId('provider-form')
    const labels = Array.from(form.querySelectorAll('label, span.text-sm')).map((node) => node.textContent?.trim())
    const order = ['Name auf dem Knopf', 'Kurzname', 'Aussteller (Issuer)', 'Client-ID', 'Client-Geheimnis', 'Rückleitadresse für den Anbieter']
    expect(labels.filter((label) => order.includes(label ?? ''))).toEqual(order)
    fireEvent.change(within(form).getByLabelText('Name auf dem Knopf'), { target: { value: 'Mein Firmen-Login' } })
    expect(within(form).getByLabelText('Kurzname')).toHaveValue('mein-firmen-login')
    expect(screen.getByTestId('provider-redirect')).toHaveTextContent('https://music.example.com/api/oidc/mein-firmen-login/callback')
  })

  it('shows a form error at its field', async () => {
    serve({ '/api/settings': SETTINGS, '/api/oidc/admin/providers': [], '/api/oidc/authentik/address': ADDRESS })
    vi.spyOn(api, 'post').mockRejectedValue(new ApiError(422, 'x', 'oidc_issuer_mismatch', { field: 'issuer' }))
    wrap(<SignInCards />)
    fireEvent.click(await screen.findByRole('button', { name: 'Anbieter hinzufügen' }))
    const form = screen.getByTestId('provider-form')
    fireEvent.change(within(form).getByLabelText('Name auf dem Knopf'), { target: { value: 'SSO' } })
    fireEvent.change(within(form).getByLabelText('Aussteller (Issuer)'), { target: { value: 'https://sso.example.com' } })
    fireEvent.change(within(form).getByLabelText('Client-ID'), { target: { value: 'abc' } })
    fireEvent.submit(form)
    expect(await within(form).findByRole('alert')).toHaveTextContent('Der Anbieter nennt sich anders als eingetragen.')
  })

  it('asks with the numbers before an entry is removed', async () => {
    serve({
      '/api/settings': SETTINGS,
      '/api/oidc/admin/providers/1/impact': { issuer_change: 0, count: 2, only: 1, only_names: [] },
      '/api/oidc/admin/providers': [provider()],
      '/api/oidc/authentik/address': ADDRESS,
    })
    const removed = vi.spyOn(api, 'delete').mockResolvedValue({ count: 2, only: 1 } as never)
    wrap(<SignInCards />)
    fireEvent.click(await screen.findByRole('button', { name: 'Entfernen' }))
    const question = await screen.findByRole('dialog')
    expect(question).toHaveTextContent('„authentik“ entfernen? 2 Konten verlieren die Verknüpfung, für 1 davon ist es der einzige Weg herein.')
    fireEvent.click(within(question).getByRole('button', { name: 'Entfernen' }))
    await waitFor(() => expect(removed).toHaveBeenCalledWith('/api/oidc/admin/providers/1'))
  })

  it('asks before another issuer drops the links', async () => {
    serve({
      '/api/settings': SETTINGS,
      '/api/oidc/admin/providers/1/impact': { issuer_change: 2, count: 2, only: 0, only_names: [] },
      '/api/oidc/admin/providers': [provider()],
      '/api/oidc/authentik/address': ADDRESS,
    })
    const saved = vi.spyOn(api, 'put').mockResolvedValue({} as never)
    wrap(<SignInCards />)
    fireEvent.click(await screen.findByRole('button', { name: 'Bearbeiten' }))
    const form = screen.getByTestId('provider-form')
    fireEvent.change(within(form).getByLabelText('Aussteller (Issuer)'), { target: { value: 'https://other.example.com' } })
    fireEvent.submit(form)
    expect(await screen.findByText('Ein anderer Aussteller ist ein anderer Anbieter. 2 Konten müssen sich danach neu verknüpfen.')).toBeInTheDocument()
    expect(saved).not.toHaveBeenCalled()
  })

  it('lists the steps of the authentik button by name, with the reason of the failed one', async () => {
    serve({ '/api/settings': SETTINGS, '/api/oidc/admin/providers': [], '/api/oidc/authentik/address': ADDRESS })
    vi.spyOn(api, 'post').mockResolvedValue({
      ok: false,
      steps: [
        { key: 'reached', ok: true, reason: '', status: 0 },
        { key: 'signingKey', ok: false, reason: 'token', status: 403 },
      ],
    } as never)
    wrap(<SignInCards />)
    fireEvent.change(await screen.findByLabelText('Adresse von authentik'), { target: { value: 'https://auth.example.com' } })
    fireEvent.change(screen.getByLabelText('API-Token'), { target: { value: 'secret-token' } })
    fireEvent.click(screen.getByRole('button', { name: 'Einrichten' }))
    const steps = await screen.findByTestId('authentik-steps')
    expect(steps).toHaveTextContent('Verbindung zu authentik')
    expect(steps).toHaveTextContent('Schlüssel zum Signieren')
    expect(steps).toHaveTextContent('authentik hat das Token nicht angenommen (Antwort 403).')
    expect(screen.getByLabelText('API-Token')).toHaveValue('')
  })

  it('suggests the browser address while there is none, and asks before an address leaves providers behind', async () => {
    serve({
      '/api/settings': { ...SETTINGS, public_url: '' },
      '/api/oidc/admin/providers': [],
      '/api/oidc/authentik/address': { ...ADDRESS, public_url: '' },
    })
    const put = vi.spyOn(api, 'put').mockRejectedValue(new ApiError(409, 'x', 'public_url_change', { count: 0, address: '', hand: 1 }))
    wrap(<SignInCards />)
    expect(await screen.findByTestId('authentik-proposal')).toHaveTextContent(window.location.origin)
    expect(screen.getByRole('button', { name: 'Übernehmen und einrichten' })).toBeInTheDocument()
    fireEvent.change(screen.getByLabelText('Öffentliche Adresse'), { target: { value: 'https://new.example.com' } })
    fireEvent.click(screen.getByRole('button', { name: 'Speichern' }))
    expect(await screen.findByTestId('address-question')).toHaveTextContent(
      'Bei 1 von Hand eingetragenen Anbieter musst du die Rückleitadresse dort selbst anpassen.',
    )
    put.mockResolvedValue(SETTINGS as never)
    fireEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Speichern' }))
    await waitFor(() =>
      expect(put).toHaveBeenLastCalledWith('/api/settings', { public_url: 'https://new.example.com', confirm_address: true }),
    )
  })
})

describe('my account, sign-in providers', () => {
  it('asks the password again before linking and sends it along', async () => {
    serve({ '/api/oidc/me': [{ slug: 'entra', label: 'Microsoft', linked: false }] })
    const post = vi.spyOn(api, 'post').mockRejectedValue(new ApiError(400, 'Falsch', 'wrong_password'))
    wrap(<ProviderLinksSection hasPassword />, '/profil')
    const row = await screen.findByText('Microsoft')
    expect(row.closest('li')).toHaveTextContent('Nicht verknüpft')
    fireEvent.click(screen.getByRole('button', { name: 'Verknüpfen' }))
    const dialog = screen.getByRole('dialog')
    fireEvent.change(within(dialog).getByLabelText('Aktuelles Passwort'), { target: { value: 'my-password' } })
    fireEvent.click(within(dialog).getByRole('button', { name: 'Verknüpfen' }))
    await waitFor(() => expect(post).toHaveBeenCalledWith('/api/oidc/entra/link', { password: 'my-password' }))
    expect(await within(dialog).findByRole('alert')).toHaveTextContent('Falsch')
  })

  it('keeps the last way into an account without a password and says so', async () => {
    serve({ '/api/oidc/me': [{ slug: 'entra', label: 'Microsoft', linked: true }] })
    wrap(<ProviderLinksSection hasPassword={false} />, '/profil')
    expect(await screen.findByText('Dieses Konto meldet sich nur über Microsoft an.')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Lösen' })).toBeDisabled()
  })

  it('names a refused linking in words', async () => {
    serve({ '/api/oidc/me': [{ slug: 'entra', label: 'Microsoft', linked: false }] })
    wrap(<ProviderLinksSection hasPassword />, '/profil?error=oidc_subject_taken')
    expect(await screen.findByRole('alert')).toHaveTextContent('Diese Identität ist schon mit einem anderen Konto verknüpft.')
  })
})
