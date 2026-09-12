import { useEffect, useRef, useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'

import { api, errorMessage } from '../../api/client'
import type { AppSettings } from '../../api/types'
import { Button, ErrorBanner, Field, OkBanner, PageLoading, Section, Toggle } from '../../components/ui'
import { useSettings } from './useSettings'

/**
 * Welche Quellen nexbeat fragen darf. Jede ist ein Weg nach draussen und
 * bekommt deshalb einen Schalter, wie in Nexview jede Verbindung.
 *
 * Der ListenBrainz-Schluessel ist freiwillig. Seit 12.09.2026 gibt ListenBrainz die
 * Beliebtheit einzelner Kuenstler teils nur noch mit Schluessel heraus.
 */
export function AdminSourcesSettings() {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const { query, settings, save } = useSettings()
  const filled = useRef(false)
  const [draft, setDraft] = useState({ source_listenbrainz: true, source_deezer: true })
  // Bleibt leer: Ein versehentliches Speichern soll den Schluessel nicht ersetzen.
  const [token, setToken] = useState('')

  useEffect(() => {
    if (!settings || filled.current) return
    filled.current = true
    setDraft({ source_listenbrainz: settings.source_listenbrainz, source_deezer: settings.source_deezer })
  }, [settings])

  const check = useMutation({
    mutationFn: () => api.post<{ ok: boolean; user_name: string }>('/api/settings/test/listenbrainz', { token: token || null }),
  })
  const remove = useMutation({
    mutationFn: () => api.delete<AppSettings>('/api/settings/secret/listenbrainz_token'),
    onSuccess: (data) => {
      queryClient.setQueryData(['settings'], data)
      check.reset()
    },
  })

  if (query.isPending) return <PageLoading />

  const tokenSet = Boolean(settings?.listenbrainz_token_set)

  return (
    <Section title={t('sources.title')} intro={t('sources.intro')}>
      <div className="rounded-xl border border-ink-700 bg-ink-900/60 px-4 py-3">
        <p className="text-sm font-medium text-mist-200">MusicBrainz · Cover Art Archive</p>
        <p className="mt-0.5 text-xs text-mist-500">{t('sources.musicbrainz')}</p>
      </div>
      <Toggle
        label="ListenBrainz"
        hint={t('sources.listenbrainz')}
        checked={draft.source_listenbrainz}
        onChange={(checked) => setDraft({ ...draft, source_listenbrainz: checked })}
      />
      <div className="flex flex-col gap-2 pl-7">
        <Field
          label={t('sources.listenbrainzToken')}
          type="password"
          value={token}
          onChange={(event) => {
            setToken(event.target.value)
            check.reset()
          }}
          placeholder={tokenSet ? settings?.listenbrainz_token : ''}
          hint={tokenSet ? t('common.secretSetHint') : t('sources.listenbrainzTokenHint')}
          autoComplete="new-password"
        />
        <div className="flex flex-wrap items-center gap-3">
          <Button type="button" variant="ghost" onClick={() => check.mutate()} loading={check.isPending} disabled={!token && !tokenSet}>
            {t('sources.listenbrainzTokenCheck')}
          </Button>
          {tokenSet && (
            <Button type="button" variant="ghost" onClick={() => remove.mutate()} loading={remove.isPending}>
              {t('sources.listenbrainzTokenRemove')}
            </Button>
          )}
          {check.isSuccess && <span className="text-sm text-ok-500">{t('sources.listenbrainzTokenOk', { user: check.data.user_name })}</span>}
          {check.isError && <span className="text-sm text-bad-500">{errorMessage(check.error)}</span>}
        </div>
        {remove.isError && <ErrorBanner message={errorMessage(remove.error)} />}
      </div>
      <Toggle label="Deezer" hint={t('sources.deezer')} checked={draft.source_deezer} onChange={(checked) => setDraft({ ...draft, source_deezer: checked })} />
      {save.isError && <ErrorBanner message={errorMessage(save.error)} />}
      {save.isSuccess && <OkBanner message={t('common.saved')} />}
      <div>
        <Button
          onClick={() => save.mutate(token ? { ...draft, listenbrainz_token: token } : draft, { onSuccess: () => setToken('') })}
          loading={save.isPending}
        >
          {t('common.save')}
        </Button>
      </div>
    </Section>
  )
}
