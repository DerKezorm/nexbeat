import { useEffect, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { useSearchParams } from 'react-router-dom'

import { api, errorMessage, storedError } from '../../api/client'
import { Button, ErrorBanner, OkBanner, Section } from '../../components/ui'

type Link = { slug: string; label: string; linked: boolean }

const LINKS_KEY = ['oidc-links']

/**
 * Das eigene Konto mit einem Anmeldeanbieter verknuepfen, wie in nexdeck.
 *
 * ⚠️ Nur so kommt ein bestehendes Konto an einen Anbieter, nie ueber die Mailadresse. Der Ruecksprung
 * landet wieder hier, mit `oidc_linked` oder `oidc_error` in der Adresse.
 */
export function ProviderLinksSection() {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const [params, setParams] = useSearchParams()
  const [notice, setNotice] = useState<{ ok: boolean; text: string } | null>(null)
  const links = useQuery({ queryKey: LINKS_KEY, queryFn: () => api.get<Link[]>('/api/oidc/links') })

  const linkedSlug = params.get('oidc_linked')
  const failure = params.get('oidc_error')
  useEffect(() => {
    if (!linkedSlug && !failure) return
    if (failure) setNotice({ ok: false, text: storedError(failure) ?? failure })
    setParams({}, { replace: true })
    // Nur beim Ankommen, nicht bei jedem Neuzeichnen.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])
  // Die Beschriftung kennt erst die Liste; solange sie laedt, steht der Kurzname da.
  const [arrivedFrom] = useState(linkedSlug)
  const arrivedLabel = links.data?.find((entry) => entry.slug === arrivedFrom)?.label ?? arrivedFrom

  const start = useMutation({
    mutationFn: (slug: string) => api.post<{ url: string }>(`/api/oidc/links/${encodeURIComponent(slug)}`),
    onSuccess: ({ url }) => window.location.assign(url),
  })
  const unlink = useMutation({
    mutationFn: (slug: string) => api.delete<void>(`/api/oidc/links/${encodeURIComponent(slug)}`),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: LINKS_KEY }),
  })

  if (!links.data || links.data.length === 0) return null

  return (
    <Section title={t('profile.providers')} intro={t('profile.providersIntro')}>
      {arrivedFrom && !notice && <OkBanner message={t('profile.providerLinkedOk', { label: arrivedLabel })} />}
      {notice && !notice.ok && <ErrorBanner message={notice.text} />}
      {start.isError && <ErrorBanner message={errorMessage(start.error)} />}
      {unlink.isError && <ErrorBanner message={errorMessage(unlink.error)} />}
      <ul className="flex flex-col gap-2">
        {links.data.map((entry) => (
          <li key={entry.slug} className="flex flex-wrap items-center gap-3 rounded-xl border border-ink-700 px-4 py-3">
            <span className="flex-1 text-sm font-medium text-mist-100">{entry.label}</span>
            {entry.linked && <span className="text-xs text-mist-500">{t('profile.providerLinked')}</span>}
            {entry.linked ? (
              <Button
                type="button"
                variant="ghost"
                loading={unlink.isPending && unlink.variables === entry.slug}
                onClick={() => unlink.mutate(entry.slug)}
              >
                {t('profile.providerUnlink')}
              </Button>
            ) : (
              <Button
                type="button"
                variant="ghost"
                loading={start.isPending && start.variables === entry.slug}
                onClick={() => start.mutate(entry.slug)}
              >
                {t('profile.providerLink')}
              </Button>
            )}
          </li>
        ))}
      </ul>
    </Section>
  )
}
