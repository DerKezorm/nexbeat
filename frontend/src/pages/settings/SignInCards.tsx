/**
 * Einstellungen, System, Anmeldung: drei Karten untereinander, wie der Bauplan "Anmeldung mit OIDC und authentik"
 * (Teil 04) sie fuer jede nex-App vorgibt. Reihenfolge, Wortlaut und Verhalten kommen von dort, die Bauteile (Karte,
 * Schalter, Feld, Knopf, Rueckfrage) sind die von nexbeat.
 *
 * 1. Anmeldung: Anmeldung mit Passwort (an, solange kein Anbieter aktiv ist) und die oeffentliche Adresse.
 * 2. Anmeldeanbieter: die Liste mit ihren Marken und dem Ziehgriff, das Formular als Dialog.
 * 3. authentik in einem Schritt: Adresse, Token, "Einrichten", der Blueprint, die Schritte mit dem Grund eines Fehlers.
 *    Ohne oeffentliche Adresse schlaegt die Karte die des Browsers vor und traegt nichts Geratenes ein.
 */
import { useEffect, useId, useState } from 'react'
import type { FormEvent, ReactNode } from 'react'
import { createPortal } from 'react-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'

import { ApiError, api, download, errorMessage } from '../../api/client'
import type { AuthentikResult, OidcProvider, OidcProviderForm } from '../../api/types'
import { AddressQuestion } from '../../components/AddressQuestion'
import { ConfirmDialog } from '../../components/ConfirmDialog'
import { Symbol } from '../../components/Symbol'
import { Button, ErrorBanner, Field, OkBanner, PageLoading, Section, Toggle } from '../../components/ui'
import {
  authentikIssuerChange,
  authentikProposal,
  authentikProxyWarning,
  authentikReasonKey,
  authentikRedirect,
  authentikStale,
  authentikStepKey,
  oidcErrorKey,
  oidcFormErrorKey,
  slugFromLabel,
  type AuthentikAddress,
} from '../../vendor/nexoidc/oidc'
import { questionOf, type AddressQuestionValues } from '../../lib/addressQuestion'
import { useSettings } from './useSettings'

const PROVIDERS_KEY = ['oidc-admin-providers']
const ADDRESS_KEY = ['oidc-authentik-address']

export function SignInCards() {
  const providers = useQuery({
    queryKey: PROVIDERS_KEY,
    queryFn: () => api.get<OidcProvider[]>('/api/oidc/admin/providers'),
  })
  const { query } = useSettings()
  if (query.isPending || providers.isPending) return <PageLoading />
  const list = providers.data ?? []
  return (
    <div className="flex flex-col gap-6">
      <SignInCard anyActive={list.some((entry) => entry.enabled)} />
      <ProvidersCard providers={list} />
      <AuthentikCard />
    </div>
  )
}

// --- Karte 1: Anmeldung ----------------------------------------------------------------------------------------------

function SignInCard({ anyActive }: { anyActive: boolean }) {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const { settings, save } = useSettings()
  const [address, setAddress] = useState(settings?.public_url ?? '')
  const [question, setQuestion] = useState<AddressQuestionValues | null>(null)
  // Die authentik-Karte kann die Adresse inzwischen gespeichert haben.
  useEffect(() => setAddress(settings?.public_url ?? ''), [settings?.public_url])

  const saveAddress = (confirm: boolean) => {
    setQuestion(null)
    save.mutate(confirm ? { public_url: address, confirm_address: true } : { public_url: address }, {
      onError: (error) => setQuestion(questionOf(error)),
      onSuccess: () => void queryClient.invalidateQueries({ queryKey: ADDRESS_KEY }),
    })
  }
  if (!settings) return null
  const asked = save.isError && questionOf(save.error) !== null

  return (
    <Section title={t('oidc.admin.signInTitle')}>
      <Toggle
        label={t('oidc.admin.password')}
        hint={t('oidc.admin.passwordHint')}
        checked={settings.password_login}
        // Ohne aktiven Anbieter kaeme ausser dem Betreiber niemand herein: der Schalter bleibt an.
        disabled={settings.password_login && !anyActive}
        onChange={(value) => save.mutate({ password_login: value })}
      />
      <form
        className="flex flex-wrap items-end gap-3"
        onSubmit={(event: FormEvent) => {
          event.preventDefault()
          saveAddress(false)
        }}
      >
        <div className="min-w-64 flex-1">
          <Field
            label={t('oidc.admin.address')}
            value={address}
            onChange={(event) => setAddress(event.target.value)}
            placeholder="https://music.example.com"
            hint={t('oidc.admin.addressHint')}
          />
        </div>
        <Button type="submit" loading={save.isPending} className="mb-6">
          {t('common.save')}
        </Button>
      </form>
      {save.isError && !asked && <ErrorBanner message={errorMessage(save.error)} />}
      {save.isSuccess && <OkBanner message={t('common.saved')} />}
      <ConfirmDialog
        open={question !== null}
        title={t('oidc.admin.address')}
        description={question ? <AddressQuestion question={question} /> : null}
        confirmLabel={t('common.save')}
        loading={save.isPending}
        onCancel={() => setQuestion(null)}
        onConfirm={() => saveAddress(true)}
      />
    </Section>
  )
}

// --- Karte 2: Anmeldeanbieter ----------------------------------------------------------------------------------------

/** Derselbe Aussteller, wie auch immer am Ende geschrieben (``same_issuer`` des Servers ohne Platzhalter). */
function sameIssuer(a: string, b: string): boolean {
  return a.trim().replace(/\/+$/, '') === b.trim().replace(/\/+$/, '')
}

function ProvidersCard({ providers }: { providers: OidcProvider[] }) {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const [editing, setEditing] = useState<OidcProvider | 'new' | null>(null)
  const [removing, setRemoving] = useState<{ entry: OidcProvider; count: number; only: number } | null>(null)
  const [dragged, setDragged] = useState<number | null>(null)
  const refresh = () => {
    void queryClient.invalidateQueries({ queryKey: PROVIDERS_KEY })
    void queryClient.invalidateQueries({ queryKey: ADDRESS_KEY })
  }
  const readOnly = providers.some((entry) => !entry.editable)

  const order = useMutation({
    mutationFn: (ids: number[]) => api.put('/api/oidc/admin/providers/order', { ids }),
    onSettled: refresh,
  })
  const impact = useMutation({
    mutationFn: (entry: OidcProvider) =>
      api.get<{ count: number; only: number }>(`/api/oidc/admin/providers/${entry.id}/impact`),
    onSuccess: (found, entry) => setRemoving({ entry, count: found.count, only: found.only }),
  })
  const remove = useMutation({
    mutationFn: (entry: OidcProvider) => api.delete(`/api/oidc/admin/providers/${entry.id}`),
    onSuccess: () => {
      setRemoving(null)
      refresh()
    },
  })

  const move = (from: number, to: number) => {
    if (from === to || to < 0 || to >= providers.length) return
    const ids = providers.map((entry) => entry.id)
    const [taken] = ids.splice(from, 1)
    ids.splice(to, 0, taken)
    order.mutate(ids)
  }

  return (
    <Section title={t('oidc.admin.providersTitle')} intro={t('oidc.admin.providersText')}>
      {providers.length === 0 ? (
        <p className="text-sm text-mist-500">{t('oidc.admin.empty')}</p>
      ) : (
        <ul className="flex flex-col gap-2" data-testid="provider-list">
          {providers.map((entry, index) => (
            <li
              key={entry.id}
              className={'flex flex-wrap items-center gap-3 rounded-xl border border-ink-700 px-4 py-3 ' + (dragged === index ? 'opacity-50' : '')}
              draggable={!readOnly}
              onDragStart={() => setDragged(index)}
              onDragEnd={() => setDragged(null)}
              onDragOver={(event) => event.preventDefault()}
              onDrop={(event) => {
                event.preventDefault()
                if (dragged !== null) move(dragged, index)
                setDragged(null)
              }}
            >
              {/* Griff und Name bleiben auch auf dem Handy in einer Zeile. */}
              <div className="flex min-w-0 flex-1 basis-full items-center gap-2 sm:basis-auto">
                {!readOnly && providers.length > 1 && (
                  <button
                    type="button"
                    className="cursor-grab rounded px-1 text-mist-500 hover:text-mist-200"
                    aria-label={t('signin.order', { name: entry.label })}
                    onKeyDown={(event) => {
                      if (event.key === 'ArrowUp') move(index, index - 1)
                      if (event.key === 'ArrowDown') move(index, index + 1)
                    }}
                  >
                    <span aria-hidden="true">⋮⋮</span>
                  </button>
                )}
                <div className="min-w-0 flex-1">
                  <p className="truncate text-sm font-medium text-mist-100">{entry.label}</p>
                  <p className="truncate text-xs text-mist-500">{entry.issuer}</p>
                </div>
              </div>
              <span className="flex flex-wrap items-center gap-1.5 text-xs">
                <span className={'rounded-full px-2 py-0.5 ' + (entry.enabled ? 'bg-ok-500/10 text-ok-500' : 'border border-ink-700 text-mist-500')}>
                  {entry.enabled ? t('oidc.admin.active') : t('oidc.admin.inactive')}
                </span>
                {entry.managed === 'authentik' && (
                  <span className="rounded-full border border-accent-500/40 px-2 py-0.5 text-accent-400">{t('oidc.admin.managed')}</span>
                )}
              </span>
              {entry.editable && (
                <span className="flex gap-2">
                  <Button type="button" variant="ghost" className="px-4 py-1.5 text-xs" onClick={() => setEditing(entry)}>
                    {t('oidc.admin.edit')}
                  </Button>
                  <Button
                    type="button"
                    variant="ghost"
                    className="border-bad-500/40 px-4 py-1.5 text-xs text-bad-500 hover:bg-bad-500/10 hover:text-bad-500"
                    loading={impact.isPending && impact.variables?.id === entry.id}
                    onClick={() => {
                      remove.reset()
                      impact.mutate(entry)
                    }}
                  >
                    {t('oidc.admin.remove')}
                  </Button>
                </span>
              )}
            </li>
          ))}
        </ul>
      )}
      {(order.isError || impact.isError) && <ErrorBanner message={errorMessage(order.error ?? impact.error)} />}
      {!readOnly && (
        <div>
          <Button type="button" onClick={() => setEditing('new')}>
            {t('oidc.admin.add')}
          </Button>
        </div>
      )}
      {editing !== null && (
        <ProviderDialog
          entry={editing === 'new' ? null : editing}
          onClose={() => setEditing(null)}
          onSaved={() => {
            setEditing(null)
            refresh()
          }}
        />
      )}
      <ConfirmDialog
        open={removing !== null}
        title={t('oidc.admin.remove')}
        description={removing ? t('oidc.admin.removeConfirm', { name: removing.entry.label, count: removing.count, only: removing.only }) : ''}
        confirmLabel={t('oidc.admin.remove')}
        loading={remove.isPending}
        error={remove.isError ? errorMessage(remove.error) : null}
        onCancel={() => setRemoving(null)}
        onConfirm={() => removing && remove.mutate(removing.entry)}
      />
    </Section>
  )
}

const EMPTY: OidcProviderForm = {
  label: '',
  slug: '',
  issuer: '',
  client_id: '',
  client_secret: '',
  scopes: 'openid profile email',
  enabled: true,
  auto_create: false,
  trusts_second_factor: true,
}

type FieldName = 'label' | 'slug' | 'issuer' | 'client_id' | 'client_secret' | 'scopes' | 'id'

/** Ein Fenster ueber der Seite, wie die Rueckfrage gebaut; Escape und ein Klick daneben schliessen. */
function Modal({ title, onClose, children }: { title: string; onClose: () => void; children: ReactNode }) {
  const titleId = useId()
  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === 'Escape') onClose()
    }
    document.addEventListener('keydown', onKeyDown)
    const previous = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    return () => {
      document.removeEventListener('keydown', onKeyDown)
      document.body.style.overflow = previous
    }
  }, [onClose])
  return createPortal(
    <div
      className="fixed inset-0 z-40 flex items-center justify-center bg-scrim p-4 backdrop-blur-sm"
      role="dialog"
      aria-modal="true"
      aria-labelledby={titleId}
      onClick={(event) => {
        if (event.target === event.currentTarget) onClose()
      }}
    >
      <div className="max-h-[90vh] w-full max-w-lg overflow-y-auto rounded-2xl border border-ink-700 bg-ink-850 p-6 shadow-2xl shadow-black/60">
        <h2 id={titleId} className="text-lg font-bold tracking-tight">
          {title}
        </h2>
        {children}
      </div>
    </div>,
    document.body,
  )
}

/** Das Formular eines Anbieters als Dialog, Felder in der Reihenfolge des Bauplans. */
function ProviderDialog({ entry, onClose, onSaved }: { entry: OidcProvider | null; onClose: () => void; onSaved: () => void }) {
  const { t } = useTranslation()
  const { settings } = useSettings()
  const [form, setForm] = useState<OidcProviderForm>(
    entry
      ? {
          label: entry.label,
          issuer: entry.issuer,
          client_id: entry.client_id,
          client_secret: '',
          scopes: entry.scopes,
          enabled: entry.enabled,
          auto_create: entry.auto_create,
          trusts_second_factor: entry.trusts_second_factor,
        }
      : EMPTY,
  )
  // Der Kurzname folgt dem Namen auf dem Knopf, bis er selbst getippt wird.
  const [slugTyped, setSlugTyped] = useState(false)
  const [copied, setCopied] = useState(false)
  const [problem, setProblem] = useState<{ field: FieldName; text: string } | null>(null)
  const [confirmIssuer, setConfirmIssuer] = useState<number | null>(null)
  const set = (change: Partial<OidcProviderForm>) => setForm((current) => ({ ...current, ...change }))

  const slug = entry ? entry.slug : slugTyped ? (form.slug ?? '') : slugFromLabel(form.label)
  const base = (settings?.public_url || window.location.origin).replace(/\/+$/, '')
  const redirect = entry ? entry.redirect_uri : `${base}/api/oidc/${slug || '…'}/callback`

  const problemOf = (error: unknown): { field: FieldName; text: string } => {
    if (!(error instanceof ApiError)) return { field: 'id', text: errorMessage(error) }
    const field = (typeof error.data?.field === 'string' ? error.data.field : 'id') as FieldName
    const key = oidcFormErrorKey(error.code) ?? oidcErrorKey(error.code)
    return { field, text: key ? t(key) : error.message }
  }

  const save = useMutation({
    mutationFn: () => {
      const body = { ...form, slug: entry ? undefined : slug }
      return entry ? api.put(`/api/oidc/admin/providers/${entry.id}`, body) : api.post('/api/oidc/admin/providers', body)
    },
    onSuccess: onSaved,
    onError: (error) => setProblem(problemOf(error)),
  })

  async function submit(event: FormEvent) {
    event.preventDefault()
    setProblem(null)
    // Ein anderer Aussteller ist ein anderer Anbieter: erst sagen, wie viele Konten sich neu verknuepfen muessen.
    if (entry && entry.links > 0 && !sameIssuer(entry.issuer, form.issuer)) {
      try {
        const found = await api.get<{ issuer_change: number }>(
          `/api/oidc/admin/providers/${entry.id}/impact?issuer=${encodeURIComponent(form.issuer.trim())}`,
        )
        if (found.issuer_change > 0) {
          setConfirmIssuer(found.issuer_change)
          return
        }
      } catch (error) {
        setProblem(problemOf(error))
        return
      }
    }
    save.mutate()
  }

  const at = (field: FieldName) =>
    problem?.field === field ? (
      <p role="alert" className="-mt-2 text-xs text-bad-500">
        {problem.text}
      </p>
    ) : null

  return (
    <Modal title={entry ? `${t('oidc.admin.edit')}: ${entry.label}` : t('oidc.admin.add')} onClose={() => !save.isPending && onClose()}>
      <form className="mt-4 flex flex-col gap-4" onSubmit={(event) => void submit(event)} data-testid="provider-form">
        <Field label={t('oidc.admin.label')} value={form.label} onChange={(event) => set({ label: event.target.value })} required />
        {at('label')}
        {entry ? (
          <p className="text-xs text-mist-500">
            {t('oidc.admin.slug')}: <code className="font-mono text-mist-300">{entry.slug}</code>
          </p>
        ) : (
          <>
            <Field
              label={t('oidc.admin.slug')}
              value={slug}
              onChange={(event) => {
                setSlugTyped(true)
                set({ slug: event.target.value.toLowerCase() })
              }}
              hint={t('oidc.admin.slugHint')}
              maxLength={40}
            />
            {at('slug')}
          </>
        )}
        <Field
          label={t('oidc.admin.issuer')}
          value={form.issuer}
          onChange={(event) => set({ issuer: event.target.value })}
          placeholder="https://auth.example.com/application/o/nexbeat/"
          hint={t('oidc.admin.issuerHint')}
          required
        />
        {at('issuer')}
        <Field label={t('oidc.admin.clientId')} value={form.client_id} onChange={(event) => set({ client_id: event.target.value })} required />
        {at('client_id')}
        <Field
          label={t('oidc.admin.secret')}
          type="password"
          autoComplete="new-password"
          value={form.client_secret}
          onChange={(event) => set({ client_secret: event.target.value })}
          placeholder={entry?.has_secret ? t('oidc.admin.secretKept') : ''}
        />
        {at('client_secret')}
        <div className="flex flex-col gap-1.5">
          <span className="text-sm font-medium text-mist-300">{t('oidc.admin.redirect')}</span>
          <div className="flex items-center gap-2 rounded-lg border border-ink-700 bg-ink-900 px-3 py-2">
            <code className="min-w-0 flex-1 truncate text-xs text-mist-200" data-testid="provider-redirect">
              {redirect}
            </code>
            <button
              type="button"
              onClick={() => void navigator.clipboard?.writeText(redirect).then(() => setCopied(true))}
              className="text-xs font-semibold text-accent-500 hover:text-accent-400"
            >
              {copied ? t('common.copied') : t('common.copy')}
            </button>
          </div>
        </div>
        <Toggle label={t('oidc.admin.enabled')} checked={form.enabled} onChange={(enabled) => set({ enabled })} />
        <Toggle
          label={t('oidc.admin.autoCreate')}
          hint={t('oidc.admin.autoCreateHint')}
          checked={form.auto_create}
          onChange={(auto_create) => set({ auto_create })}
        />
        {/* "Der Anbieter prueft den zweiten Faktor selbst" entfaellt: nexbeat hat keinen eigenen zweiten Faktor. */}
        <details open={problem?.field === 'scopes' || undefined}>
          <summary className="cursor-pointer text-xs text-mist-400">{t('signin.more')}</summary>
          <div className="mt-3">
            <Field label={t('oidc.admin.scopes')} value={form.scopes} onChange={(event) => set({ scopes: event.target.value })} />
            {at('scopes')}
          </div>
        </details>
        {at('id')}
        <div className="flex flex-wrap justify-end gap-2">
          <Button type="button" variant="ghost" onClick={onClose} disabled={save.isPending}>
            {t('common.cancel')}
          </Button>
          <Button type="submit" loading={save.isPending}>
            {t('common.save')}
          </Button>
        </div>
      </form>
      <ConfirmDialog
        open={confirmIssuer !== null}
        title={t('oidc.admin.issuer')}
        description={t('oidc.admin.issuerChangeConfirm', { count: confirmIssuer ?? 0 })}
        confirmLabel={t('common.save')}
        loading={save.isPending}
        onCancel={() => setConfirmIssuer(null)}
        onConfirm={() => {
          setConfirmIssuer(null)
          save.mutate()
        }}
      />
    </Modal>
  )
}

// --- Karte 3: authentik in einem Schritt -----------------------------------------------------------------------------

function AuthentikCard() {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const [values, setValues] = useState({ url: '', token: '' })
  const [steps, setSteps] = useState<AuthentikResult | null>(null)
  // Der Knopf hielt an, bevor er etwas schrieb: ein anderer Aussteller, so viele Konten muessten sich neu verknuepfen.
  const [asking, setAsking] = useState<{ count: number; adopt: boolean } | null>(null)
  // "Nur uebernehmen" hielt an: Das Speichern der Adresse laesst eine Rueckleitadresse zurueck, die ein Anbieter kennt.
  const [question, setQuestion] = useState<AddressQuestionValues | null>(null)
  const address = useQuery({
    queryKey: ADDRESS_KEY,
    queryFn: () => api.get<AuthentikAddress>('/api/oidc/authentik/address'),
  })
  const refresh = () => {
    void queryClient.invalidateQueries({ queryKey: ADDRESS_KEY })
    void queryClient.invalidateQueries({ queryKey: PROVIDERS_KEY })
    void queryClient.invalidateQueries({ queryKey: ['settings'] })
  }

  // Solange nexbeat keine oeffentliche Adresse hat, bietet die Karte die des Browsers an (nie eine geratene).
  const proposal = authentikProposal(window.location.origin, import.meta.env.BASE_URL)
  const view = address.data ?? null
  const missing = view !== null && view.public_url === ''
  const stale = authentikStale(view)

  const run = useMutation({
    mutationFn: ({ confirm, adopt }: { confirm: boolean; adopt: boolean }) =>
      api.post<AuthentikResult>('/api/oidc/authentik/setup', {
        url: values.url,
        token: values.token,
        confirm_issuer_change: confirm,
        public_url: adopt ? proposal : '',
      }),
    onMutate: () => {
      setSteps(null)
      setAsking(null)
    },
    onSuccess: (answer, { adopt }) => {
      // Keine Niederlage: Der Knopf wartet auf das Ja des Betreibers, geaendert ist nichts. Das Token bleibt fuer
      // den zweiten Lauf stehen.
      const count = authentikIssuerChange(answer)
      if (count !== null) {
        setAsking({ count, adopt })
        return
      }
      setSteps(answer)
      // Das Token galt nur fuer diesen Lauf, es bleibt auch nicht in der Seite stehen.
      setValues((current) => ({ ...current, token: '' }))
      refresh()
    },
  })
  const adoptOnly = useMutation({
    mutationFn: (confirm: boolean) =>
      api.post<AuthentikAddress>('/api/oidc/authentik/address', confirm ? { public_url: proposal, confirm: true } : { public_url: proposal }),
    onMutate: () => setQuestion(null),
    onSuccess: refresh,
    onError: (error) => setQuestion(questionOf(error)),
  })
  const blueprint = useMutation({ mutationFn: () => download('/api/oidc/authentik/blueprint', 'nexbeat-authentik.yaml') })

  const adoptProblem =
    adoptOnly.isError && questionOf(adoptOnly.error) === null
      ? adoptOnly.error instanceof ApiError && adoptOnly.error.code === 'public_url_invalid'
        ? t('oidc.authentik.why.unusable')
        : errorMessage(adoptOnly.error)
      : null

  return (
    <Section title={t('oidc.authentik.title')} intro={t('oidc.authentik.text')}>
      {missing && view && (
        <div className="flex flex-col gap-1.5 rounded-xl border border-warn-500/40 bg-warn-500/10 px-4 py-3 text-xs text-warn-500" data-testid="authentik-no-address">
          <p>{t('oidc.authentik.noAddress')}</p>
          <p className="font-mono text-sm break-all text-mist-100" data-testid="authentik-proposal">
            {proposal}
          </p>
          <p className="break-all">
            {t('oidc.admin.redirect')}: <code className="font-mono">{authentikRedirect(proposal, view)}</code>
          </p>
          {authentikProxyWarning(proposal, view) && <p data-testid="authentik-proxy-warning">{t('oidc.authentik.proxyWarning', { address: view.seen })}</p>}
        </div>
      )}
      {stale && (
        <p className="rounded-xl border border-warn-500/40 bg-warn-500/10 px-4 py-3 text-xs text-warn-500" data-testid="authentik-stale">
          {t('oidc.authentik.stale', { address: stale })}
        </p>
      )}
      <form
        className="flex flex-col gap-4"
        onSubmit={(event: FormEvent) => {
          event.preventDefault()
          run.mutate({ confirm: false, adopt: missing })
        }}
      >
        <div className="grid gap-4 sm:grid-cols-2">
          <Field
            label={t('oidc.authentik.url')}
            value={values.url}
            onChange={(event) => setValues({ ...values, url: event.target.value })}
            placeholder="https://auth.example.com"
          />
          <Field
            label={t('oidc.authentik.token')}
            type="password"
            autoComplete="new-password"
            value={values.token}
            onChange={(event) => setValues({ ...values, token: event.target.value })}
          />
        </div>
        <div className="flex flex-wrap items-center gap-3">
          <Button type="submit" loading={run.isPending} disabled={!values.url.trim() || !values.token.trim()}>
            {missing ? t('oidc.authentik.adopt') : t('oidc.authentik.run')}
          </Button>
          {missing && (
            <Button type="button" variant="ghost" loading={adoptOnly.isPending} onClick={() => adoptOnly.mutate(false)}>
              {t('oidc.authentik.adoptOnly')}
            </Button>
          )}
          <button
            type="button"
            className="inline-flex items-center gap-1.5 text-sm text-accent-400 hover:underline"
            onClick={() => blueprint.mutate()}
          >
            <Symbol name="download" />
            {t('oidc.authentik.blueprint')}
          </button>
        </div>
      </form>
      {run.isPending && (
        <p className="text-xs text-mist-400" aria-live="polite">
          {t('oidc.authentik.asking')}
        </p>
      )}
      {run.isError && <ErrorBanner message={errorMessage(run.error)} />}
      {adoptProblem && <ErrorBanner message={adoptProblem} />}
      {blueprint.isError && (
        <ErrorBanner
          message={
            blueprint.error instanceof ApiError && blueprint.error.code === 'public_url_needed'
              ? t('oidc.authentik.why.public_url_needed')
              : errorMessage(blueprint.error)
          }
        />
      )}
      {steps && (
        <ol className="flex flex-col gap-1.5 text-sm" data-testid="authentik-steps">
          {steps.steps.map((step) => {
            const name = authentikStepKey(step.key)
            const why = step.ok ? null : authentikReasonKey(step.reason)
            return (
              <li key={step.key} className="flex gap-2">
                <span className={step.ok ? 'text-ok-500' : 'text-bad-500'} aria-hidden="true">
                  {step.ok ? '✓' : '✗'}
                </span>
                <span>
                  <span className={step.ok ? 'text-mist-200' : 'font-medium text-bad-500'}>{name ? t(name) : step.key}</span>
                  {why && <span className="block text-xs text-mist-400">{t(why, { status: step.status ?? 0, count: steps.count ?? 0 })}</span>}
                </span>
              </li>
            )
          })}
        </ol>
      )}
      <ConfirmDialog
        open={asking !== null}
        title={t('oidc.authentik.title')}
        description={t('oidc.admin.issuerChangeConfirm', { count: asking?.count ?? 0 })}
        confirmLabel={t('oidc.authentik.run')}
        loading={run.isPending}
        onCancel={() => setAsking(null)}
        onConfirm={() => run.mutate({ confirm: true, adopt: asking?.adopt ?? false })}
      />
      <ConfirmDialog
        open={question !== null}
        title={t('oidc.admin.address')}
        description={question ? <AddressQuestion question={question} /> : null}
        confirmLabel={t('common.save')}
        loading={adoptOnly.isPending}
        onCancel={() => setQuestion(null)}
        onConfirm={() => adoptOnly.mutate(true)}
      />
    </Section>
  )
}
