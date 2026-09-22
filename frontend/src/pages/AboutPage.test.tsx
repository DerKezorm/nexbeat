import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen } from '@testing-library/react'
import type { ReactNode } from 'react'
import { MemoryRouter } from 'react-router-dom'

import { api } from '../api/client'
import type { AboutInfo, Me } from '../api/types'
import { AuthContext, type AuthState } from '../auth/AuthContext'
import { UserMenu } from '../components/UserMenu'
import { WhatsNewAfterUpdate } from '../components/WhatsNewAfterUpdate'
import i18n, { startI18n } from '../i18n'
import { latestVersion } from '../lib/whatsnew'
import { AboutPage } from './AboutPage'

const QUOTA = { limit: null, used: 0, remaining: null, period: 'week', resets_at: '2026-09-28T00:00:00Z' }

function auth(user: Partial<Me>): AuthState {
  return {
    status: 'ready',
    user: { username: 'lena', display_name: 'Lena', is_admin: false, quota: QUOTA, ...user } as Me,
    config: null,
    needsSetup: false,
    login: vi.fn(),
    startSession: vi.fn(),
    logout: vi.fn(),
    refreshUser: vi.fn(async () => undefined),
    updateUser: vi.fn(),
  }
}

function show(node: ReactNode, value: AuthState) {
  const queries = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  return render(
    <QueryClientProvider client={queries}>
      <AuthContext.Provider value={value}>
        <MemoryRouter>{node}</MemoryRouter>
      </AuthContext.Provider>
    </QueryClientProvider>,
  )
}

const BASE: AboutInfo = {
  version: '1.1.0',
  repo_url: 'https://github.com/DerKezorm/nexbeat',
  releases_url: 'https://github.com/DerKezorm/nexbeat/releases',
  license: 'AGPL-3.0-or-later',
  update: null,
}

beforeAll(async () => {
  await startI18n('de')
})

afterEach(() => {
  vi.restoreAllMocks()
})

describe('about nexbeat', () => {
  it('shows a user the version and no update section', async () => {
    vi.spyOn(api, 'get').mockResolvedValue(BASE)
    show(<AboutPage />, auth({ seen_version: '1.1.0' }))
    expect(await screen.findByText('nexbeat 1.1.0')).toBeInTheDocument()
    expect(screen.queryByText(i18n.t('about.updates'))).not.toBeInTheDocument()
  })

  it('tells an admin about a newer version and how to update', async () => {
    const update = { enabled: true, latest: 'v1.2.0', available: true, checked_at: '2026-09-22T09:12:00Z' }
    vi.spyOn(api, 'get').mockResolvedValue({ ...BASE, update })
    show(<AboutPage />, auth({ is_admin: true, seen_version: '1.1.0' }))
    expect(await screen.findByText(i18n.t('about.newer', { version: '1.2.0' }))).toBeInTheDocument()
    expect(screen.getByText('docker compose pull && docker compose up -d')).toBeInTheDocument()
  })

  it('switches the check off on the same page', async () => {
    const update = { enabled: true, latest: 'v1.1.0', available: false, checked_at: '2026-09-22T09:12:00Z' }
    vi.spyOn(api, 'get').mockResolvedValue({ ...BASE, update })
    const put = vi.spyOn(api, 'put').mockResolvedValue({})
    show(<AboutPage />, auth({ is_admin: true, seen_version: '1.1.0' }))
    fireEvent.click(await screen.findByLabelText(i18n.t('about.updateCheck')))
    await vi.waitFor(() => expect(put).toHaveBeenCalledWith('/api/settings', { update_check: false }))
  })

  it('opens the window again from the page', async () => {
    vi.spyOn(api, 'get').mockResolvedValue(BASE)
    show(<AboutPage />, auth({ seen_version: latestVersion() }))
    fireEvent.click(await screen.findByRole('button', { name: i18n.t('about.whatsNew', { version: latestVersion() }) }))
    expect(screen.getByRole('dialog')).toBeInTheDocument()
  })
})

describe('what is new after an update', () => {
  it('opens once for an account that has not seen the newest version, closes at once and notes it', async () => {
    const patch = vi.spyOn(api, 'patch').mockResolvedValue({ seen_version: latestVersion() })
    const value = auth({ seen_version: null })
    show(<WhatsNewAfterUpdate />, value)
    const dialog = screen.getByRole('dialog')
    expect(dialog).toHaveTextContent(i18n.t('whatsNew.title', { version: latestVersion() }))
    // Ein Abschnitt fuer Admins bleibt Nutzern verborgen.
    expect(dialog).not.toHaveTextContent('GitHub')
    fireEvent.click(screen.getByRole('button', { name: i18n.t('whatsNew.gotIt') }))
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    expect(patch).toHaveBeenCalledWith('/api/auth/me', { seen_version: latestVersion() })
  })

  it('shows admins their sections too', () => {
    show(<WhatsNewAfterUpdate />, auth({ is_admin: true, seen_version: null }))
    expect(screen.getByRole('dialog')).toHaveTextContent('GitHub')
  })

  it('stays closed for an account that saw it', () => {
    show(<WhatsNewAfterUpdate />, auth({ seen_version: latestVersion() }))
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })
})

describe('the menu', () => {
  it('lists about nexbeat for everyone and marks a newer version for admins only', () => {
    vi.spyOn(api, 'get').mockResolvedValue([])
    const { unmount } = show(<UserMenu />, auth({ update_available: true }))
    fireEvent.click(screen.getByRole('button', { expanded: false }))
    // Ein Nutzer sieht den Eintrag, aber keinen Hinweis auf eine neuere Fassung.
    expect(screen.getByRole('menuitem', { name: i18n.t('nav.about') })).toBeInTheDocument()
    unmount()
    show(<UserMenu />, auth({ is_admin: true, update_available: true }))
    fireEvent.click(screen.getByRole('button', { expanded: false }))
    expect(screen.getByRole('menuitem', { name: new RegExp(`${i18n.t('nav.about')}\\s*${i18n.t('about.newBadge')}`) })).toBeInTheDocument()
  })
})
