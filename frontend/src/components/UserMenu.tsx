import { useEffect, useRef, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { NavLink, useLocation } from 'react-router-dom'

import { api } from '../api/client'
import type { MusicRequest } from '../api/types'
import { useAuth } from '../auth/useAuth'
import { Avatar } from './Avatar'

type Entry = { to: string; labelKey: string; adminOnly?: boolean; badge?: number }

/**
 * Aufklappmenue am eigenen Namen, wie in Nexview: Alles Persoenliche und die
 * Verwaltung liegen hier, das Hauptmenue bleibt beim Entdecken.
 */
export function UserMenu() {
  const { t } = useTranslation()
  const { user, logout } = useAuth()
  const [open, setOpen] = useState(false)
  const container = useRef<HTMLDivElement>(null)
  const location = useLocation()

  const pending = useQuery({
    queryKey: ['admin-requests', 'pending_approval'],
    queryFn: () => api.get<MusicRequest[]>('/api/admin/requests?status=pending_approval'),
    enabled: user?.is_admin ?? false,
    refetchInterval: 60_000,
  })
  const waiting = pending.data?.length ?? 0

  useEffect(() => setOpen(false), [location.pathname])

  useEffect(() => {
    if (!open) return
    function onClick(event: MouseEvent) {
      if (!container.current?.contains(event.target as Node)) setOpen(false)
    }
    function onKey(event: KeyboardEvent) {
      if (event.key === 'Escape') setOpen(false)
    }
    document.addEventListener('mousedown', onClick)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('mousedown', onClick)
      document.removeEventListener('keydown', onKey)
    }
  }, [open])

  if (!user) return null
  const name = user.display_name || user.username
  const quota = user.quota
  const entries: Entry[] = (
    [
      { to: '/profil', labelKey: 'nav.profile' },
      { to: '/anfragen', labelKey: 'nav.myRequests' },
      { to: '/admin/anfragen', labelKey: 'nav.allRequests', adminOnly: true, badge: waiting },
      { to: '/admin/einstellungen', labelKey: 'nav.settings', adminOnly: true },
    ] as Entry[]
  ).filter((entry) => !entry.adminOnly || user.is_admin)

  return (
    <div ref={container} className="relative">
      <button
        type="button"
        onClick={() => setOpen((current) => !current)}
        aria-expanded={open}
        aria-haspopup="menu"
        className="flex items-center gap-2 rounded-full border border-ink-700 py-1 pr-3 pl-1 transition-colors hover:border-accent-600"
      >
        <span className="relative">
          <Avatar name={name} />
          {waiting > 0 && <span className="absolute -top-0.5 -right-0.5 h-2.5 w-2.5 rounded-full bg-accent-500 ring-2 ring-ink-950" />}
        </span>
        <span className="hidden max-w-32 truncate text-sm text-mist-300 sm:inline">{name}</span>
        <svg viewBox="0 0 20 20" className="h-3.5 w-3.5 text-mist-500" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
          <path d="m6 8 4 4 4-4" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      </button>

      {open && (
        <div
          role="menu"
          className="absolute right-0 z-30 mt-2 w-60 overflow-hidden rounded-xl border border-ink-700 bg-ink-850 py-1 shadow-2xl shadow-black/60"
        >
          <div className="border-b border-ink-700 px-4 py-3">
            <div className="flex items-center gap-3">
              <Avatar name={name} className="h-9 w-9" />
              <div className="min-w-0">
                <p className="truncate text-sm font-semibold">{name}</p>
                <p className="truncate text-xs text-mist-600">{t(user.is_admin ? 'users.roleAdmin' : 'users.roleUser')}</p>
              </div>
            </div>
            <dl className="mt-3 border-t border-ink-700/60 pt-3">
              <dt className="text-[10px] font-medium tracking-wide text-mist-600 uppercase">{t(`quota.period_${quota.period}`)}</dt>
              <dd className={'text-sm tabular-nums ' + (quota.limit !== null && quota.used >= quota.limit ? 'text-bad-500' : 'text-mist-300')}>
                {quota.limit === null ? t('quota.unlimited') : t('quota.usedOf', { used: quota.used, limit: quota.limit })}
              </dd>
            </dl>
          </div>

          {entries.map((entry) => (
            <NavLink
              key={entry.to}
              to={entry.to}
              role="menuitem"
              className={({ isActive }) =>
                'flex items-center gap-2 px-4 py-2.5 text-sm transition-colors ' +
                (isActive ? 'bg-accent-500/15 text-accent-400' : 'text-mist-300 hover:bg-ink-800 hover:text-mist-100')
              }
            >
              {t(entry.labelKey)}
              {entry.badge ? (
                <span className="ml-auto rounded-full bg-accent-500 px-1.5 text-[10px] font-bold text-white">{entry.badge}</span>
              ) : null}
            </NavLink>
          ))}

          <button
            type="button"
            role="menuitem"
            onClick={() => void logout()}
            className="w-full border-t border-ink-700 px-4 py-2.5 text-left text-sm text-mist-300 transition-colors hover:bg-ink-800 hover:text-accent-400"
          >
            {t('nav.logout')}
          </button>
        </div>
      )}
    </div>
  )
}
