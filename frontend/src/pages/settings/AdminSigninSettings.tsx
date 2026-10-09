import { useState } from 'react'
import type { FormEvent } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'

import { ApiError, api, errorMessage } from '../../api/client'
import { ConfirmDialog } from '../../components/ConfirmDialog'
import { Symbol } from '../../components/Symbol'
import { Button, ErrorBanner, Field, OkBanner, PageLoading, SELECT_CLASS, Section, Toggle } from '../../components/ui'
import { useSettings } from './useSettings'

type Provider = {
  id: number
  slug: string
  label: string
  issuer_url: string
  client_id: string
  has_secret: boolean
  scopes: string
  enabled: boolean
  auto_create: boolean
  default_role: 'user' | 'admin'
  linked_accounts: number
}

type Draft = Omit<Provider, 'id' | 'has_secret' | 'linked_accounts'> & { client_secret: string }

type SetupResult = { ok: boolean; steps: { key: string; ok: boolean; detail: string }[] }

const EMPTY: Draft = {
  slug: '',
  label: '',
  issuer_url: '',
  client_id: '',
  client_secret: '',
  scopes: 'openid profile email',
  enabled: true,
  auto_create: true,
  default_role: 'user',
}

const STEP_LABELS: Record<string, string> = {
  reached: 'signin.stepReached',
  signingKey: 'signin.stepSigningKey',
  mapping: 'signin.stepMapping',
  provider: 'signin.stepProvider',
  application: 'signin.stepApplication',
  filled: 'signin.stepFilled',
}

const PROVIDERS_KEY = ['oidc-providers']

/** Anmeldung ueber OpenID Connect, wie in nexdiary: eine Karte, die Anbieter und darunter authentik in einem Schritt. */
export function AdminSigninSettings() {
  const { settings, query: settingsQuery } = useSettings()
  if (settingsQuery.isPending) return <PageLoading />
  const base = (settings?.public_url ?? '').replace(/\/+$/, '')
  return (
    <ProvidersCard base={base} />
  )
}

function AuthentikBlock({ base }: { base: string }) {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const [url, setUrl] = useState('')
  const [token, setToken] = useState('')
  const run = useMutation({
    mutationFn: () => api.post<SetupResult>('/api/oidc/authentik/setup', { url, token }),
    onSuccess: () => {
      // Der Token galt nur fuer diesen Lauf, er bleibt auch nicht in der Seite stehen.
      setToken('')
      void queryClient.invalidateQueries({ queryKey: PROVIDERS_KEY })
    },
  })
  const blueprint = useMutation({
    mutationFn: () => api.get<{ filename: string; content: string }>('/api/oidc/authentik/blueprint'),
    onSuccess: ({ filename, content }) => {
      const link = document.createElement('a')
      link.href = URL.createObjectURL(new Blob([content], { type: 'application/yaml' }))
      link.download = filename
      link.click()
      URL.revokeObjectURL(link.href)
    },
  })

  return (
    <div className="flex flex-col gap-4 border-t border-ink-700 pt-4">
      <div>
        <h3 className="text-sm font-semibold text-mist-200">{t('signin.authentikTitle')}</h3>
        <p className="mt-1 text-sm text-mist-500">{t('signin.authentikIntro')}</p>
      </div>
      {!base && <p className="text-sm text-warn-500">{t('signin.authentikNoAddress')}</p>}
      <form
        className="flex flex-col gap-4"
        onSubmit={(event: FormEvent) => {
          event.preventDefault()
          run.mutate()
        }}
      >
        <div className="grid gap-4 sm:grid-cols-2">
          <Field
            label={t('signin.authentikUrl')}
            type="url"
            value={url}
            onChange={(event) => setUrl(event.target.value)}
            placeholder="https://auth.example.com"
          />
          <Field
            label={t('signin.authentikToken')}
            type="password"
            autoComplete="new-password"
            value={token}
            onChange={(event) => setToken(event.target.value)}
            hint={t('signin.authentikTokenHint')}
          />
        </div>
        {run.isError && <ErrorBanner message={errorMessage(run.error)} />}
        {blueprint.isError && <ErrorBanner message={errorMessage(blueprint.error)} />}
        <div className="flex flex-wrap items-center gap-3">
          <Button type="submit" loading={run.isPending} disabled={!base || !url.trim() || !token.trim()}>
            {t('signin.authentikRun')}
          </Button>
          <Button type="button" variant="ghost" loading={blueprint.isPending} disabled={!base} onClick={() => blueprint.mutate()}>
            {!blueprint.isPending && <Symbol name="download" />}
            {t('signin.authentikBlueprint')}
          </Button>
        </div>
        <p className="text-xs text-mist-500">{t('signin.authentikBlueprintHint')}</p>
      </form>
      {run.data && (
        <div className="flex flex-col gap-2">
          <ol className="flex flex-col gap-1 text-sm" data-testid="authentik-steps">
            {run.data.steps.map((step) => (
              <li key={step.key} className={step.ok ? 'text-mist-300' : 'text-accent-400'}>
                {step.ok ? '✓' : '✗'} {t(STEP_LABELS[step.key] ?? step.key)}: <span className="text-mist-500">{step.detail}</span>
              </li>
            ))}
          </ol>
          {run.data.ok && <OkBanner message={t('signin.authentikDone')} />}
        </div>
      )}
    </div>
  )
}

function ProvidersCard({ base }: { base: string }) {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const providers = useQuery({ queryKey: PROVIDERS_KEY, queryFn: () => api.get<Provider[]>('/api/oidc/providers') })
  const [draft, setDraft] = useState<Draft>(EMPTY)
  const [editing, setEditing] = useState<Provider | null>(null)
  const [deleting, setDeleting] = useState<Provider | null>(null)
  const [strands, setStrands] = useState<string | null>(null)

  const refresh = () => void queryClient.invalidateQueries({ queryKey: PROVIDERS_KEY })
  const save = useMutation({
    mutationFn: () =>
      editing ? api.patch<Provider>(`/api/oidc/providers/${editing.id}`, draft) : api.post<Provider>('/api/oidc/providers', draft),
    onSuccess: () => {
      setDraft(EMPTY)
      setEditing(null)
      refresh()
    },
  })
  const remove = useMutation({
    mutationFn: ({ provider, force }: { provider: Provider; force: boolean }) =>
      api.delete<void>(`/api/oidc/providers/${provider.id}${force ? '?force=true' : ''}`),
    onSuccess: () => {
      setDeleting(null)
      setStrands(null)
      refresh()
    },
    onError: (error) => {
      // Konten ohne Passwort haengen nur an diesem Anbieter: erst sagen, wer, dann erst endgueltig.
      if (error instanceof ApiError && error.code === 'oidc_provider_strands') setStrands(error.message)
    },
  })

  function edit(provider: Provider) {
    const { slug, label, issuer_url, client_id, scopes, enabled, auto_create, default_role } = provider
    setDraft({ slug, label, issuer_url, client_id, client_secret: '', scopes, enabled, auto_create, default_role })
    setEditing(provider)
    save.reset()
  }

  function cancel() {
    setDraft(EMPTY)
    setEditing(null)
    save.reset()
  }

  const issuerChanged = editing !== null && editing.issuer_url.replace(/\/+$/, '') !== draft.issuer_url.trim().replace(/\/+$/, '')
  const ready = draft.slug && draft.label.trim() && draft.issuer_url.trim() && draft.client_id.trim()

  return (
    <Section title={t('signin.providersTitle')} intro={t('signin.providersIntro')}>
      {providers.isPending ? (
        <PageLoading />
      ) : providers.isError ? (
        <ErrorBanner message={errorMessage(providers.error)} />
      ) : providers.data.length === 0 ? (
        <p className="text-sm text-mist-500">{t('signin.none')}</p>
      ) : (
        <ul className="flex flex-col gap-2">
          {providers.data.map((provider) => (
            <li
              key={provider.id}
              className={
                'flex flex-wrap items-center gap-3 rounded-xl border px-4 py-3 ' +
                (editing?.id === provider.id ? 'border-accent-500' : 'border-ink-700')
              }
            >
              <div className="min-w-0 flex-1 basis-full sm:basis-auto">
                <p className="text-sm font-medium text-mist-100">
                  {provider.label}
                  {!provider.enabled && <span className="ml-2 text-xs text-mist-600">({t('signin.off')})</span>}
                </p>
                <p className="truncate text-xs text-mist-500">{provider.issuer_url}</p>
                <p className="text-xs text-mist-600">{t('signin.linkedAccounts', { count: provider.linked_accounts })}</p>
              </div>
              <Button type="button" variant="ghost" onClick={() => edit(provider)} aria-pressed={editing?.id === provider.id}>
                {t('signin.edit')}
              </Button>
              <Button
                type="button"
                variant="ghost"
                onClick={() => {
                  remove.reset()
                  setStrands(null)
                  setDeleting(provider)
                }}
              >
                {t('signin.delete')}
              </Button>
            </li>
          ))}
        </ul>
      )}

      <form
        className="flex flex-col gap-4 border-t border-ink-700 pt-4"
        onSubmit={(event: FormEvent) => {
          event.preventDefault()
          save.mutate()
        }}
      >
        <h3 className="text-sm font-semibold text-mist-200">
          {editing ? t('signin.editTitle', { label: editing.label }) : t('signin.addTitle')}
        </h3>
        <div className="grid gap-4 sm:grid-cols-2">
          <Field
            label={t('signin.slug')}
            value={draft.slug}
            onChange={(event) => setDraft({ ...draft, slug: event.target.value.toLowerCase().replace(/[^a-z0-9-]/g, '') })}
            hint={t('signin.slugHint')}
            maxLength={40}
            required
          />
          <Field label={t('signin.label')} value={draft.label} onChange={(event) => setDraft({ ...draft, label: event.target.value })} maxLength={80} required />
          <Field
            label={t('signin.issuer')}
            type="url"
            value={draft.issuer_url}
            onChange={(event) => setDraft({ ...draft, issuer_url: event.target.value })}
            hint={t('signin.issuerHint')}
            required
          />
          <Field label={t('signin.clientId')} value={draft.client_id} onChange={(event) => setDraft({ ...draft, client_id: event.target.value })} required />
          <Field
            label={t('signin.clientSecret')}
            type="password"
            autoComplete="new-password"
            value={draft.client_secret}
            onChange={(event) => setDraft({ ...draft, client_secret: event.target.value })}
            hint={editing?.has_secret ? t('common.secretSetHint') : undefined}
          />
          <Field label={t('signin.scopes')} value={draft.scopes} onChange={(event) => setDraft({ ...draft, scopes: event.target.value })} />
          <label className="flex flex-col gap-1.5">
            <span className="text-sm font-medium text-mist-300">{t('signin.role')}</span>
            <select
              value={draft.default_role}
              onChange={(event) => setDraft({ ...draft, default_role: event.target.value as Draft['default_role'] })}
              className={SELECT_CLASS}
            >
              <option value="user">{t('signin.roleUser')}</option>
              <option value="admin">{t('signin.roleAdmin')}</option>
            </select>
          </label>
        </div>
        <Toggle
          label={t('signin.autoCreate')}
          hint={t('signin.autoCreateHint')}
          checked={draft.auto_create}
          onChange={(auto_create) => setDraft({ ...draft, auto_create })}
        />
        {editing && (
          <Toggle
            label={t('signin.enabled')}
            hint={t('signin.enabledHint')}
            checked={draft.enabled}
            onChange={(enabled) => setDraft({ ...draft, enabled })}
          />
        )}
        {base && (
          <p className="text-xs break-all text-mist-500">
            {t('signin.redirect', { url: `${base}/api/auth/oidc/${draft.slug || '…'}/callback` })}
          </p>
        )}
        <p className="text-xs text-mist-500">{t('signin.entraHint')}</p>
        {issuerChanged && <p className="text-sm text-warn-500">{t('signin.issuerChanged')}</p>}
        {save.isError && <ErrorBanner message={errorMessage(save.error)} />}
        {save.isSuccess && <OkBanner message={t('common.saved')} />}
        <div className="flex flex-wrap gap-3">
          <Button type="submit" loading={save.isPending} disabled={!ready}>
            {editing ? t('common.save') : t('signin.add')}
          </Button>
          {editing && (
            <Button type="button" variant="ghost" onClick={cancel}>
              {t('common.cancel')}
            </Button>
          )}
        </div>
      </form>

      <AuthentikBlock base={base} />

      <ConfirmDialog
        open={deleting !== null}
        title={t('signin.deleteTitle', { label: deleting?.label ?? '' })}
        description={strands ?? t('signin.deleteBody')}
        error={remove.isError && !strands ? errorMessage(remove.error) : null}
        confirmLabel={strands ? t('signin.deleteAnyway') : t('signin.delete')}
        loading={remove.isPending}
        onConfirm={() => deleting && remove.mutate({ provider: deleting, force: strands !== null })}
        onCancel={() => {
          setDeleting(null)
          setStrands(null)
        }}
      />
    </Section>
  )
}
