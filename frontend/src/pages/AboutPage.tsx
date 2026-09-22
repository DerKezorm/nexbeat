import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'

import { api, errorMessage } from '../api/client'
import type { AboutInfo } from '../api/types'
import { useAuth } from '../auth/useAuth'
import { Logo } from '../components/Logo'
import { Button, ErrorBanner, PageLoading, PageTitle, Section, Toggle } from '../components/ui'
import { WhatsNewDialog } from '../components/WhatsNewDialog'
import { formatDateTime } from '../lib/format'
import { entryFor, latestVersion } from '../lib/whatsnew'

function Outside({ href, children }: { href: string; children: string }) {
  return (
    <a href={href} target="_blank" rel="noreferrer noopener" className="text-accent-400 underline decoration-accent-500/40 underline-offset-4 hover:decoration-accent-400">
      {children}
    </a>
  )
}

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-wrap items-baseline justify-between gap-x-6 gap-y-1 border-b border-ink-700/60 py-2.5 last:border-b-0">
      <dt className="text-sm text-mist-500">{label}</dt>
      <dd className="text-sm font-medium text-mist-200">{children}</dd>
    </div>
  )
}

/**
 * Ueber nexbeat: fuer alle Fassung, Herkunft, Lizenz und "Was ist neu" (entschieden am 22.09.2026).
 *
 * ⚠️ Der Schalter fuer die Update-Pruefung steht hier, wo auch ihr Ergebnis erscheint, und die Seite sagt, dass dafuer
 * etwas nach draussen geht. Wie in nexmail: eine Ausnahme, die man verschweigt, ist ein gebrochenes Versprechen.
 * Nur Admins sehen den Abschnitt; Nutzer koennen nichts aktualisieren.
 */
export function AboutPage() {
  const { t, i18n } = useTranslation()
  const { user, refreshUser } = useAuth()
  const queryClient = useQueryClient()
  const [reading, setReading] = useState(false)
  const about = useQuery({ queryKey: ['about'], queryFn: () => api.get<AboutInfo>('/api/about') })
  const check = useMutation({
    mutationFn: () => api.post<AboutInfo>('/api/about/check'),
    onSuccess: (data) => {
      queryClient.setQueryData(['about'], data)
      void refreshUser()
    },
  })
  const toggle = useMutation({
    mutationFn: (enabled: boolean) => api.put('/api/settings', { update_check: enabled }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['about'] })
      void refreshUser()
    },
  })

  if (about.isPending) return <PageLoading />
  if (about.isError || !about.data) return <ErrorBanner message={errorMessage(about.error)} />

  const info = about.data
  const update = info.update
  const newest = latestVersion(info.version)
  const entry = newest ? entryFor(newest, i18n.language) : null

  return (
    <div className="flex max-w-3xl flex-col gap-6">
      <PageTitle>{t('about.title')}</PageTitle>

      <Section title={`nexbeat ${info.version}`} intro={t('about.tagline')}>
        <div className="flex items-center gap-3">
          <Logo />
        </div>
        <dl>
          <Row label={t('about.version')}>{info.version}</Row>
          <Row label={t('about.source')}>
            <Outside href={info.repo_url}>{info.repo_url.replace('https://', '')}</Outside>
          </Row>
          <Row label={t('about.license')}>GNU AGPL v3.0</Row>
          <Row label={t('about.data')}>{t('about.dataSources')}</Row>
        </dl>
        {entry && newest && (
          <div>
            <Button variant="ghost" onClick={() => setReading(true)}>
              {t('about.whatsNew', { version: newest })}
            </Button>
          </div>
        )}
      </Section>

      {update && (
        <Section title={t('about.updates')} intro={t('about.updatesIntro')}>
          <Toggle
            label={t('about.updateCheck')}
            checked={update.enabled}
            onChange={(enabled) => toggle.mutate(enabled)}
            disabled={toggle.isPending}
          />
          {update.enabled &&
            (update.available && update.latest ? (
              <div role="status" className="rounded-xl border border-accent-500/40 bg-accent-500/10 px-4 py-3 text-sm">
                <p className="font-semibold text-accent-400">{t('about.newer', { version: update.latest.replace(/^v/, '') })}</p>
                <p className="mt-1 text-mist-300">
                  {t('about.howToUpdate')} <code className="text-mist-100">docker compose pull && docker compose up -d</code>
                </p>
                <p className="mt-1">
                  <Outside href={info.releases_url}>{t('about.releaseNotes')}</Outside>
                </p>
              </div>
            ) : update.checked_at ? (
              <p className="text-sm text-ok-500">{t('about.current', { when: formatDateTime(update.checked_at, i18n.language) })}</p>
            ) : (
              <p className="text-sm text-mist-500">{t('about.notChecked')}</p>
            ))}
          {update.enabled && (
            <div>
              <Button variant="ghost" onClick={() => check.mutate()} loading={check.isPending}>
                {t('about.checkNow')}
              </Button>
            </div>
          )}
          {(check.isError || toggle.isError) && <ErrorBanner message={errorMessage(check.error ?? toggle.error)} />}
        </Section>
      )}

      {reading && entry && newest && user && (
        <WhatsNewDialog version={newest} entry={entry} isAdmin={user.is_admin} onClose={() => setReading(false)} />
      )}
    </div>
  )
}
