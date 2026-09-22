import { useEffect, useRef, useState } from 'react'
import type { FormEvent } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'

import { ApiError, api, errorMessage, storedError } from '../../api/client'
import type { NexcrateFacts, NexcratePairing, NexcrateStatus } from '../../api/types'
import { useAuth } from '../../auth/useAuth'
import { ConfirmDialog } from '../../components/ConfirmDialog'
import { Symbol } from '../../components/Symbol'
import { Button, ErrorBanner, Field, OkBanner, PageLoading, Section, Toggle } from '../../components/ui'
import { useSettings } from './useSettings'

/** nexcrates eigener Code und Satz hinter einer Ablehnung, fuer die Fehlersuche. Ohne ihn stand nur "abgelehnt" da. */
function Detail({ text }: { text: unknown }) {
  if (typeof text !== 'string' || !text) return null
  return <p className="font-mono text-xs break-all text-mist-500">{text}</p>
}

function detailOf(error: unknown): unknown {
  return error instanceof ApiError ? error.data?.detail : null
}

function remaining(until: string | undefined, now: number): string {
  if (!until) return ''
  const seconds = Math.max(0, Math.round((new Date(until).getTime() - now) / 1000))
  return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, '0')}`
}

function Fact({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div className="rounded-xl border border-ink-700 bg-ink-900 p-3 text-sm">
      <p className="text-mist-500">{label}</p>
      <p className="font-semibold">{value}</p>
      {hint && <p className="text-xs text-mist-500">{hint}</p>}
    </div>
  )
}

/** Was die Musik-Fassung in nexcrate braucht. Einrichten muss es der Betreiber dort, nicht hier. */
function Readiness({ facts }: { facts: NexcrateFacts }) {
  const { t } = useTranslation()
  if (!facts.music) return <p role="note" className="rounded-xl border border-warn-500/40 bg-warn-500/10 px-4 py-3 text-sm text-warn-500">{t('nexcrate.noMusic')}</p>
  const version = facts.music_versions[0]
  const notes: string[] = []
  if (!facts.can_request) notes.push(t('nexcrate.noRequestScope'))
  if (!version) notes.push(t('nexcrate.noVersion'))
  if (notes.length > 0) {
    return (
      <div role="note" className="flex flex-col gap-1 rounded-xl border border-warn-500/40 bg-warn-500/10 px-4 py-3 text-sm text-warn-500">
        {notes.map((note) => (
          <p key={note}>{note}</p>
        ))}
      </div>
    )
  }
  // "Automatik aus" haelt eine Anfrage nicht auf: nexcrate sucht einen Suchwunsch auch dann.
  const blocking = version.reasons.filter((reason) => reason !== 'automatic_off')
  const automaticOff = version.reasons.includes('automatic_off')
  return (
    <div className="flex flex-col gap-2">
      {blocking.length > 0 ? (
        <div role="note" className="rounded-xl border border-warn-500/40 bg-warn-500/10 px-4 py-3 text-sm text-warn-500">
          <p className="font-semibold">{t('nexcrate.notReadyTitle')}</p>
          <p>{t('nexcrate.notReadyText')}</p>
          <ul className="mt-1 list-disc pl-5">
            {blocking.map((reason) => (
              <li key={reason}>{t(`nexcrate.reason.${reason}`, { defaultValue: reason })}</li>
            ))}
          </ul>
          <p className="mt-2">{t('nexcrate.notReadyWhere')}</p>
        </div>
      ) : (
        <p className="flex items-center gap-2 text-sm text-ok-500">
          <Symbol name="check" className="h-4 w-4" />
          {t('nexcrate.ready', { name: version.name })}
        </p>
      )}
      {automaticOff && <p className="text-xs text-mist-500">{t('nexcrate.automaticOff')}</p>}
    </div>
  )
}

/**
 * nexcrate verbinden (NEX-Modus): Koppeln per Bitte, die der Betreiber in nexcrate bestaetigt, oder ein
 * Schluessel von Hand. Danach Stand der Verbindung, Bereitschaft der Musik-Fassung, Probelauf, Bestand.
 *
 * ⚠️ nexbeat richtet in nexcrate nichts ein. Fehlt der Musik-Fassung etwas, steht hier nur, was.
 */
export function AdminNexcrateSettings() {
  const { t, i18n } = useTranslation()
  const queryClient = useQueryClient()
  const { refreshUser } = useAuth()
  const { query, settings, save } = useSettings()
  const filled = useRef(false)
  const [url, setUrl] = useState('')
  const [key, setKey] = useState('')
  const [manual, setManual] = useState(false)
  const [dryRun, setDryRun] = useState(false)
  const [confirmDisconnect, setConfirmDisconnect] = useState(false)
  const [ended, setEnded] = useState<'denied' | 'expired' | null>(null)
  const [now, setNow] = useState(() => Date.now())

  useEffect(() => {
    if (!settings || filled.current) return
    filled.current = true
    setUrl(settings.nexcrate_url)
    setDryRun(settings.lidarr_dry_run)
  }, [settings])

  const status = useQuery({
    queryKey: ['nexcrate-status'],
    queryFn: () => api.get<NexcrateStatus>('/api/settings/nexcrate/status'),
  })
  const pairing = useQuery({
    queryKey: ['nexcrate-pairing'],
    queryFn: () => api.get<NexcratePairing>('/api/settings/nexcrate/pairing'),
    refetchInterval: (current) =>
      current.state.data?.state === 'pending' ? (current.state.data.poll_seconds ?? 2) * 1000 : false,
  })
  const pending = pairing.data?.state === 'pending'

  useEffect(() => {
    if (!pending) return
    const timer = window.setInterval(() => setNow(Date.now()), 1000)
    return () => window.clearInterval(timer)
  }, [pending])

  const state = pairing.data?.state
  useEffect(() => {
    if (state === 'confirmed') {
      void queryClient.invalidateQueries({ queryKey: ['settings'] })
      void queryClient.invalidateQueries({ queryKey: ['nexcrate-status'] })
      void queryClient.setQueryData(['nexcrate-pairing'], { state: 'none' })
      void refreshUser()
    } else if (state === 'denied' || state === 'expired') {
      setEnded(state)
      void queryClient.setQueryData(['nexcrate-pairing'], { state: 'none' })
    }
  }, [state, queryClient, refreshUser])

  const start = useMutation({
    mutationFn: () => api.post<NexcratePairing>('/api/settings/nexcrate/pairing', { url: url.trim() }),
    onSuccess: (data) => {
      setEnded(null)
      queryClient.setQueryData(['nexcrate-pairing'], data)
    },
  })
  const cancel = useMutation({
    mutationFn: () => api.delete('/api/settings/nexcrate/pairing'),
    onSuccess: () => queryClient.setQueryData(['nexcrate-pairing'], { state: 'none' }),
  })
  const saveKey = useMutation({
    mutationFn: async () => {
      await api.put('/api/settings', { nexcrate_url: url.trim(), nexcrate_api_key: key })
      return api.post<NexcrateFacts>('/api/settings/test/nexcrate', {})
    },
    onSuccess: () => {
      setKey('')
      setManual(false)
      void queryClient.invalidateQueries({ queryKey: ['settings'] })
      void queryClient.invalidateQueries({ queryKey: ['nexcrate-status'] })
    },
  })
  const disconnect = useMutation({
    mutationFn: () => api.delete('/api/settings/secret/nexcrate_api_key'),
    onSuccess: () => {
      setConfirmDisconnect(false)
      void queryClient.invalidateQueries({ queryKey: ['settings'] })
      void queryClient.invalidateQueries({ queryKey: ['nexcrate-status'] })
    },
  })
  const sync = useMutation({
    mutationFn: () => api.post<{ artists: number }>('/api/settings/library/sync'),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ['nexcrate-status'] }),
  })
  const saveDryRun = useMutation({ mutationFn: () => api.put('/api/settings', { lidarr_dry_run: dryRun }) })

  if (query.isPending || status.isPending) return <PageLoading />

  const connected = Boolean(status.data?.connected)
  const facts = status.data?.facts
  const events = status.data?.events
  const clock = (value: string | null | undefined) =>
    value ? new Date(value).toLocaleTimeString(i18n.language, { hour: '2-digit', minute: '2-digit', second: '2-digit' }) : ''

  return (
    <div className="flex flex-col gap-4">
      <p className="flex items-start gap-2 rounded-xl border border-ink-700 bg-ink-900/70 px-4 py-3 text-sm text-mist-400">
        <Symbol name="check" className="mt-0.5 h-4 w-4 shrink-0 text-ok-500" />
        {t('nexcrate.promise')}
      </p>

      <Section title={t('nexcrate.connection')} intro={t('nexcrate.connectionIntro')}>
        {connected ? (
          <div className="flex flex-col gap-4">
            {facts ? (
              <>
                <div className="grid gap-3 sm:grid-cols-3">
                  <Fact label={t('nexcrate.connectedTo')} value={`nexcrate ${facts.version}`} hint={status.data?.url} />
                  <Fact
                    label={t('nexcrate.interface')}
                    value={`${t('nexcrate.contract', { major: facts.contract ?? '?' })}, ${facts.music ? t('nexcrate.musicOn') : t('nexcrate.musicOff')}`}
                    hint={t('nexcrate.scopes', {
                      scopes: facts.scopes.map((scope) => t(`nexcrate.scope.${scope}`, { defaultValue: scope })).join(', '),
                    })}
                  />
                  <Fact label={t('nexcrate.key')} value={`nxc_…${status.data?.key_hint ?? ''}`} hint={t('nexcrate.keyHint', { hint: status.data?.key_hint ?? '' })} />
                </div>
                <Readiness facts={facts} />
              </>
            ) : (
              status.data?.error && (
                <>
                  <ErrorBanner message={storedError(status.data.error.code) ?? status.data.error.code} />
                  <Detail text={status.data.error.detail} />
                </>
              )
            )}
            <div className="flex flex-wrap gap-3">
              <Button variant="ghost" onClick={() => void status.refetch()} loading={status.isFetching}>
                {t('nexcrate.check')}
              </Button>
              <Button variant="ghost" onClick={() => setConfirmDisconnect(true)}>
                {t('nexcrate.disconnect')}
              </Button>
            </div>
          </div>
        ) : pending ? (
          <div className="flex flex-col items-start gap-3">
            <p className="text-sm text-mist-300">{t('nexcrate.pairingText')}</p>
            <p
              aria-live="polite"
              className="rounded-2xl border border-ink-600 bg-ink-900 px-8 py-4 font-mono text-4xl tracking-[0.3em] tabular-nums"
            >
              {pairing.data?.code}
            </p>
            <p className="text-sm text-mist-500">{t('nexcrate.pairingWaiting', { time: remaining(pairing.data?.expires_at, now) })}</p>
            <Button variant="ghost" onClick={() => cancel.mutate()} loading={cancel.isPending}>
              {t('common.cancel')}
            </Button>
          </div>
        ) : (
          <div className="flex flex-col gap-4">
            {ended && (
              <p role="alert" className="rounded-xl border border-bad-500/40 bg-bad-500/10 px-4 py-3 text-sm text-bad-500">
                {ended === 'denied' ? t('nexcrate.pairingDenied') : t('nexcrate.pairingExpired')}
              </p>
            )}
            <Field
              label={t('nexcrate.url')}
              value={url}
              onChange={(event) => setUrl(event.target.value)}
              placeholder="http://nexcrate:8390"
              autoComplete="off"
            />
            <div className="flex flex-wrap gap-3">
              <Button onClick={() => start.mutate()} loading={start.isPending} disabled={!url.trim()}>
                {ended ? t('nexcrate.again') : t('nexcrate.pair')}
              </Button>
              <Button variant="ghost" aria-expanded={manual} onClick={() => setManual(!manual)}>
                {t('nexcrate.manual')}
              </Button>
            </div>
            {start.isError && <ErrorBanner message={errorMessage(start.error)} />}
            {start.isError && <Detail text={detailOf(start.error)} />}
            {manual && (
              <form
                className="flex flex-col gap-3 rounded-xl border border-ink-700 p-4"
                onSubmit={(event: FormEvent) => {
                  event.preventDefault()
                  saveKey.mutate()
                }}
              >
                <Field
                  label={t('nexcrate.apiKey')}
                  type="password"
                  value={key}
                  onChange={(event) => setKey(event.target.value)}
                  placeholder="nxc_…"
                  hint={t('nexcrate.apiKeyHint')}
                  autoComplete="new-password"
                />
                <div>
                  <Button type="submit" loading={saveKey.isPending} disabled={!url.trim() || !key}>
                    {t('nexcrate.saveAndCheck')}
                  </Button>
                </div>
                {saveKey.isError && <ErrorBanner message={errorMessage(saveKey.error)} />}
                {saveKey.isError && <Detail text={detailOf(saveKey.error)} />}
              </form>
            )}
          </div>
        )}
      </Section>

      <Section title={t('nexcrate.wholeArtist')}>
        <p className="-mt-3 text-sm text-mist-500">{t('nexcrate.wholeArtistIntro')}</p>
      </Section>

      <Section title={t('nexcrate.dryRun')} intro={t('nexcrate.dryRunIntro')}>
        <Toggle label={t('nexcrate.dryRunToggle')} hint={t('nexcrate.dryRunHint')} checked={dryRun} onChange={setDryRun} />
        {saveDryRun.isError && <ErrorBanner message={errorMessage(saveDryRun.error)} />}
        {saveDryRun.isSuccess && <OkBanner message={t('common.saved')} />}
        <div>
          <Button onClick={() => saveDryRun.mutate()} loading={saveDryRun.isPending}>
            {t('common.save')}
          </Button>
        </div>
      </Section>

      <Section title={t('nexcrate.library')} intro={t('nexcrate.libraryIntro')}>
        <div className="grid gap-3 sm:grid-cols-2">
          <Fact label={t('nexcrate.artists')} value={String(status.data?.artists ?? 0)} />
          <Fact
            label={t('nexcrate.events')}
            value={events?.connected ? t('nexcrate.eventsOn') : t('nexcrate.eventsOff')}
            hint={
              events?.error
                ? `${storedError(events.error) ?? events.error}${events.detail ? ` (${events.detail})` : ''}`
                : events?.last_event_at
                  ? t('nexcrate.eventsLast', { time: clock(events.last_event_at) })
                  : t('nexcrate.eventsNone')
            }
          />
        </div>
        <div className="flex flex-wrap items-center gap-3">
          <Button variant="ghost" onClick={() => sync.mutate()} loading={sync.isPending} disabled={!connected}>
            {t('nexcrate.syncNow')}
          </Button>
          {sync.isSuccess && <span className="text-sm text-ok-500">{t('nexcrate.synced', { count: sync.data.artists })}</span>}
        </div>
        {sync.isError && <ErrorBanner message={errorMessage(sync.error)} />}
        {sync.isError && <Detail text={detailOf(sync.error)} />}
      </Section>

      <ConfirmDialog
        open={confirmDisconnect}
        title={t('nexcrate.disconnectTitle')}
        description={t('nexcrate.disconnectText')}
        confirmLabel={t('nexcrate.disconnect')}
        onConfirm={() => disconnect.mutate()}
        onCancel={() => setConfirmDisconnect(false)}
        loading={disconnect.isPending}
        error={disconnect.isError ? errorMessage(disconnect.error) : null}
      />
      {save.isError && <ErrorBanner message={errorMessage(save.error)} />}
    </div>
  )
}
