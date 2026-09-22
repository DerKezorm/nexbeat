import { Suspense } from 'react'
import { useTranslation } from 'react-i18next'
import { NavLink, Outlet, useLocation } from 'react-router-dom'

import { useAuth } from '../auth/useAuth'
import { LoadingBar } from './LoadingBar'
import { Logo } from './Logo'
import { LanguageSwitcher, ThemeSwitcher } from './Switchers'
import { PageLoading } from './ui'
import { UserMenu } from './UserMenu'
import { WhatsNewAfterUpdate } from './WhatsNewAfterUpdate'

const NAV_ITEMS = [
  { to: '/', labelKey: 'nav.discover', end: true },
  { to: '/suche', labelKey: 'nav.search', end: false },
  { to: '/anfragen', labelKey: 'nav.requests', end: false },
]

function navClass(isActive: boolean, compact = false): string {
  return (
    (compact ? 'shrink-0 px-3 ' : 'px-3.5 ') +
    'rounded-full py-1.5 text-sm font-medium transition-colors ' +
    (isActive ? 'bg-accent-500/15 text-accent-400' : 'text-mist-500 hover:bg-ink-850 hover:text-mist-100')
  )
}

/** Rahmen der angemeldeten Ansicht, gebaut wie in Nexview: Kopfzeile, Pillen, Inhalt, Fusszeile. */
export function AppShell() {
  const { t } = useTranslation()
  const { config, user } = useAuth()
  const { pathname } = useLocation()
  // Die Seite eines Genres gehoert zum Entdecken, auch wenn ihre Adresse anders anfaengt.
  const active = (to: string, isActive: boolean) => isActive || (to === '/' && pathname.startsWith('/genre/'))

  return (
    <div className="nv-glow flex min-h-dvh flex-col">
      <header className="sticky top-0 z-20 border-b border-ink-700/80 bg-ink-950/80 backdrop-blur-xl">
        <LoadingBar />
        <div className="mx-auto flex max-w-7xl items-center gap-4 px-4 py-3 sm:px-6">
          <NavLink to="/" className="shrink-0" aria-label={t('nav.home')}>
            <Logo withWordmark />
          </NavLink>
          <nav className="hidden flex-1 items-center gap-1 md:flex" aria-label={t('nav.main')}>
            {NAV_ITEMS.map((item) => (
              <NavLink key={item.to} to={item.to} end={item.end} className={({ isActive }) => navClass(active(item.to, isActive))}>
                {t(item.labelKey)}
              </NavLink>
            ))}
          </nav>
          <div className="ml-auto flex items-center gap-2 sm:gap-3">
            <ThemeSwitcher />
            <LanguageSwitcher />
            <UserMenu />
          </div>
        </div>
        <nav className="flex gap-1 overflow-x-auto border-t border-ink-700/60 px-4 py-2 md:hidden" aria-label={t('nav.main')}>
          {NAV_ITEMS.map((item) => (
            <NavLink key={item.to} to={item.to} end={item.end} className={({ isActive }) => navClass(active(item.to, isActive), true)}>
              {t(item.labelKey)}
            </NavLink>
          ))}
        </nav>
      </header>

      <WhatsNewAfterUpdate />
      <main className="relative z-10 mx-auto w-full max-w-7xl flex-1 px-4 pt-8 pb-28 sm:px-6">
        <Suspense fallback={<PageLoading />}>
          <Outlet />
        </Suspense>
      </main>

      <footer className="relative z-10 border-t border-ink-700/60">
        <div className="mx-auto flex max-w-7xl flex-wrap items-center justify-center gap-x-4 gap-y-2 px-4 py-5 text-xs text-mist-600 sm:px-6">
          {/* Wie in Nexview: "Ueber" steht hier, fuer alle, nicht im Menue. */}
          <NavLink to="/ueber" className="transition-colors hover:text-mist-300">
            {t('about.title')}
          </NavLink>
          {config && (
            <>
              <span aria-hidden="true">·</span>
              <span className="tabular-nums">v{config.version}</span>
            </>
          )}
          <span aria-hidden="true">·</span>
          <span>{t('footer.sources')}</span>
          {user?.is_admin && user.update_available && (
            <NavLink
              to="/ueber"
              className="inline-flex items-center gap-1.5 rounded-full bg-accent-500/15 px-2.5 py-1 font-medium text-accent-400 transition-colors hover:bg-accent-500/25"
            >
              <span className="h-1.5 w-1.5 rounded-full bg-accent-400" aria-hidden="true" />
              {t('about.updateShort')}
            </NavLink>
          )}
        </div>
      </footer>
    </div>
  )
}
