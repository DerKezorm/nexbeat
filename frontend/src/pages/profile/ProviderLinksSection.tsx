import { useEffect, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { useSearchParams } from 'react-router-dom'

import { api, errorMessage } from '../../api/client'
import { ConfirmDialog } from '../../components/ConfirmDialog'
import { Button, ErrorBanner, Field, OkBanner, Section } from '../../components/ui'
import { oidcErrorKey } from '../../vendor/nexoidc/oidc'

type Link = { slug: string; label: string; linked: boolean }

const LINKS_KEY = ['oidc-me']

/**
 * Mein Konto, Anmeldeanbieter (Bauplan 04): je aktivem Anbieter eine Zeile mit Zustand und "Verknuepfen" oder
 * "Loesen". Verknuepfen fragt das eigene Passwort noch einmal (Bauplan 01), dann geht es zum Anbieter.
 *
 * ⚠️ Nur so kommt ein bestehendes Konto an einen Anbieter, nie ueber die Mailadresse. Die Rueckkehr landet wieder
 * hier, mit `linked` oder `error` in der Adresse.
 */
export function ProviderLinksSection({ hasPassword }: { hasPassword: boolean }) {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const [params, setParams] = useSearchParams()
  const [arrived] = useState(() => ({ linked: params.get('linked'), error: oidcErrorKey(params.get('error')) }))
  const [asking, setAsking] = useState<Link | null>(null)
  const [password, setPassword] = useState('')
  const links = useQuery({ queryKey: LINKS_KEY, queryFn: () => api.get<Link[]>('/api/oidc/me') })

  useEffect(() => {
    if (params.has('linked') || params.has('error')) setParams({}, { replace: true })
    // Nur beim Ankommen, nicht bei jedem Neuzeichnen.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const start = useMutation({
    mutationFn: (slug: string) => api.post<{ url: string }>(`/api/oidc/${encodeURIComponent(slug)}/link`, { password }),
    onSuccess: ({ url }) => window.location.assign(url),
  })
  const unlink = useMutation({
    mutationFn: (slug: string) => api.delete<void>(`/api/oidc/${encodeURIComponent(slug)}/link`),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: LINKS_KEY }),
  })

  if (!links.data || links.data.length === 0) return null
  const linked = links.data.filter((entry) => entry.linked)
  const only = !hasPassword && linked.length === 1 ? linked[0] : null
  const arrivedLabel = links.data.find((entry) => entry.slug === arrived.linked)?.label ?? arrived.linked

  return (
    <Section title={t('oidc.account.title')} intro={t('oidc.account.text')}>
      {arrived.linked && !arrived.error && <OkBanner message={t('profile.providerLinkedOk', { label: arrivedLabel })} />}
      {arrived.error && <ErrorBanner message={t(arrived.error)} />}
      {unlink.isError && <ErrorBanner message={errorMessage(unlink.error)} />}
      {only && <p className="text-sm text-mist-400">{t('oidc.account.only', { name: only.label })}</p>}
      <ul className="flex flex-col gap-2" data-testid="provider-links">
        {links.data.map((entry) => (
          <li key={entry.slug} className="flex flex-wrap items-center gap-3 rounded-xl border border-ink-700 px-4 py-3">
            <span className="flex-1 text-sm font-medium text-mist-100">{entry.label}</span>
            <span className={'text-xs ' + (entry.linked ? 'text-ok-500' : 'text-mist-500')}>
              {entry.linked ? t('oidc.account.linked') : t('oidc.account.notLinked')}
            </span>
            {entry.linked ? (
              <Button
                type="button"
                variant="ghost"
                loading={unlink.isPending && unlink.variables === entry.slug}
                disabled={only?.slug === entry.slug}
                onClick={() => unlink.mutate(entry.slug)}
              >
                {t('oidc.account.unlink')}
              </Button>
            ) : (
              <Button
                type="button"
                variant="ghost"
                onClick={() => {
                  start.reset()
                  setPassword('')
                  setAsking(entry)
                }}
              >
                {t('oidc.account.link')}
              </Button>
            )}
          </li>
        ))}
      </ul>
      <ConfirmDialog
        open={asking !== null}
        title={t('oidc.account.link')}
        description={t('oidc.account.text')}
        confirmLabel={t('oidc.account.link')}
        loading={start.isPending}
        error={start.isError ? errorMessage(start.error) : null}
        onCancel={() => setAsking(null)}
        onConfirm={() => asking && password && start.mutate(asking.slug)}
      >
        <div className="mt-4">
          <Field
            label={t('profile.currentPassword')}
            type="password"
            autoComplete="current-password"
            value={password}
            onChange={(event) => setPassword(event.target.value)}
          />
        </div>
      </ConfirmDialog>
    </Section>
  )
}
