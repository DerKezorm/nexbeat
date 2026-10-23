/**
 * Persoenliche API-Token: anlegen, ansehen, widerrufen. Gebaut wie in Nexview.
 *
 * ⚠️ Der Token erscheint genau einmal. Er steht nur in der Antwort aufs Anlegen, danach kennt ihn niemand
 * mehr, auch der Admin nicht. Deshalb bleibt das Fenster nach dem Anlegen offen und zeigt ihn zum
 * Kopieren, statt sich zu schliessen und den Eindruck zu lassen, man koenne ihn spaeter nachschlagen.
 */

import { useState } from 'react'
import type { FormEvent } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'

import { api, errorMessage } from '../../api/client'
import { ConfirmDialog } from '../../components/ConfirmDialog'
import { Button, ErrorBanner, Field, Section, Spinner, Toggle } from '../../components/ui'
import { formatDate } from '../../lib/format'

export type ApiKey = {
  id: number
  name: string
  preview: string
  read_only: boolean
  created_at: string
  last_used_at: string | null
}

type CreatedKey = ApiKey & { token: string }

export function ApiKeysSection() {
  const { t, i18n } = useTranslation()
  const queryClient = useQueryClient()
  const [name, setName] = useState('')
  const [readOnly, setReadOnly] = useState(true)
  const [created, setCreated] = useState<CreatedKey | null>(null)
  const [copied, setCopied] = useState(false)
  const [revoking, setRevoking] = useState<ApiKey | null>(null)

  const keys = useQuery({ queryKey: ['api-keys'], queryFn: () => api.get<ApiKey[]>('/api/auth/me/keys') })

  const create = useMutation({
    mutationFn: () => api.post<CreatedKey>('/api/auth/me/keys', { name: name.trim(), read_only: readOnly }),
    onSuccess: (key) => {
      setName('')
      setReadOnly(true)
      setCopied(false)
      setCreated(key)
      void queryClient.invalidateQueries({ queryKey: ['api-keys'] })
    },
  })

  const revoke = useMutation({
    mutationFn: (id: number) => api.delete(`/api/auth/me/keys/${id}`),
    onSuccess: () => {
      setRevoking(null)
      void queryClient.invalidateQueries({ queryKey: ['api-keys'] })
    },
  })

  return (
    <Section title={t('apiKeys.title')} intro={t('apiKeys.intro')}>
      {keys.isPending && <Spinner />}
      {keys.isError && <ErrorBanner message={errorMessage(keys.error)} />}
      {keys.data && keys.data.length === 0 && <p className="text-sm text-mist-600">{t('apiKeys.empty')}</p>}

      {keys.data && keys.data.length > 0 && (
        <ul className="flex flex-col gap-2">
          {keys.data.map((key) => (
            <li key={key.id} className="flex flex-wrap items-center gap-3 rounded-xl border border-ink-700 bg-ink-900/60 px-4 py-2.5">
              <span className="min-w-0 flex-1">
                <span className="flex flex-wrap items-center gap-2 text-sm font-medium text-mist-100">
                  {key.name}
                  {key.read_only && (
                    <span className="rounded-full bg-ink-800 px-2 py-0.5 text-xs text-mist-500">{t('apiKeys.readOnly')}</span>
                  )}
                </span>
                <span className="mt-0.5 block font-mono text-xs text-mist-600">{key.preview}…</span>
              </span>
              {/* Die nuetzlichste Angabe der Liste: Ein Token, den seit Monaten niemand benutzt hat, ist sichtbar tot. */}
              <span className="text-xs text-mist-600">
                {key.last_used_at
                  ? t('apiKeys.lastUsed', { date: formatDate(key.last_used_at, i18n.language) })
                  : t('apiKeys.neverUsed')}
              </span>
              <Button variant="ghost" className="px-3 py-1 text-xs" onClick={() => setRevoking(key)}>
                {t('apiKeys.revoke')}
              </Button>
            </li>
          ))}
        </ul>
      )}

      <form
        className="flex flex-col gap-3 border-t border-ink-700 pt-4"
        onSubmit={(event: FormEvent) => {
          event.preventDefault()
          create.mutate()
        }}
      >
        <Field
          label={t('apiKeys.nameLabel')}
          hint={t('apiKeys.nameHint')}
          value={name}
          maxLength={80}
          onChange={(event) => setName(event.target.value)}
        />
        <Toggle label={t('apiKeys.readOnly')} hint={t('apiKeys.readOnlyHint')} checked={readOnly} onChange={setReadOnly} />
        {create.isError && <ErrorBanner message={errorMessage(create.error)} />}
        <div>
          <Button type="submit" variant="ghost" loading={create.isPending} disabled={name.trim().length === 0}>
            {t('apiKeys.create')}
          </Button>
        </div>
      </form>

      <ConfirmDialog
        open={created !== null}
        title={t('apiKeys.createdTitle')}
        description={
          <p className="rounded-xl border border-warn-500/40 bg-warn-500/10 px-3 py-2 text-warn-500">{t('apiKeys.onlyOnce')}</p>
        }
        confirmLabel={t('apiKeys.done')}
        onConfirm={() => setCreated(null)}
        onCancel={() => setCreated(null)}
      >
        <div className="mt-4 flex flex-col gap-3">
          <code
            className="block rounded-xl border border-ink-700 bg-ink-900 px-3 py-2 font-mono text-sm break-all text-mist-100"
            data-testid="new-api-key"
          >
            {created?.token}
          </code>
          <div>
            <Button
              variant="ghost"
              className="px-3 py-1 text-xs"
              onClick={() => {
                if (created) void navigator.clipboard?.writeText(created.token)
                setCopied(true)
              }}
            >
              {copied ? t('apiKeys.copied') : t('apiKeys.copy')}
            </Button>
          </div>
          <p className="text-xs text-mist-500">{t('apiKeys.howToUse')}</p>
          <code className="block rounded-xl border border-ink-700 bg-ink-900 px-3 py-2 font-mono text-xs break-all text-mist-300">
            Authorization: Bearer {created?.token}
          </code>
        </div>
      </ConfirmDialog>

      <ConfirmDialog
        open={revoking !== null}
        title={t('apiKeys.revokeTitle')}
        description={t('apiKeys.revokeText', { name: revoking?.name ?? '' })}
        error={revoke.isError ? errorMessage(revoke.error) : null}
        confirmLabel={t('apiKeys.revoke')}
        loading={revoke.isPending}
        onConfirm={() => revoking && revoke.mutate(revoking.id)}
        onCancel={() => setRevoking(null)}
      />
    </Section>
  )
}
