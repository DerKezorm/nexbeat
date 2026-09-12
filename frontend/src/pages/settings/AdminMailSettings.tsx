import { useEffect, useRef, useState } from 'react'
import type { FormEvent } from 'react'
import { useMutation } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'

import { api, errorMessage } from '../../api/client'
import type { AppSettings } from '../../api/types'
import { useAuth } from '../../auth/useAuth'
import { Button, Card, ErrorBanner, Field, OkBanner, PageLoading, SELECT_CLASS } from '../../components/ui'
import { useSettings } from './useSettings'

type Security = AppSettings['smtp_security']
const SECURITIES: Security[] = ['starttls', 'ssl', 'none']
const PORT_FOR: Record<Security, string> = { starttls: '587', ssl: '465', none: '25' }

/** SMTP fuer Einladungen und Passwort-Links, gebaut wie die Mail-Seite in Nexview. */
export function AdminMailSettings() {
  const { t } = useTranslation()
  const { user } = useAuth()
  const { query, settings, save } = useSettings()
  const filled = useRef(false)
  const [draft, setDraft] = useState({
    smtp_host: '',
    smtp_port: '587',
    smtp_security: 'starttls' as Security,
    smtp_username: '',
    smtp_password: '',
    smtp_from_address: '',
    smtp_from_name: 'nexbeat',
  })
  const [recipient, setRecipient] = useState('')

  useEffect(() => {
    if (!settings || filled.current) return
    filled.current = true
    setDraft({
      smtp_host: settings.smtp_host,
      smtp_port: String(settings.smtp_port ?? 587),
      smtp_security: settings.smtp_security,
      smtp_username: settings.smtp_username,
      // Bleibt leer: Ein versehentliches Speichern soll das Passwort nicht ersetzen.
      smtp_password: '',
      smtp_from_address: settings.smtp_from_address,
      smtp_from_name: settings.smtp_from_name,
    })
  }, [settings])

  const test = useMutation({
    mutationFn: () =>
      api.post<{ ok: boolean }>('/api/settings/test/smtp', {
        host: draft.smtp_host.trim() || null,
        port: Number(draft.smtp_port) || null,
        security: draft.smtp_security,
        username: draft.smtp_username.trim() || null,
        password: draft.smtp_password || null,
      }),
  })
  const sendTest = useMutation({
    mutationFn: () => api.post<{ sent: boolean }>('/api/settings/test-mail', { to: recipient.trim() || null }),
  })

  if (query.isPending) return <PageLoading />

  function update(patch: Partial<typeof draft>) {
    setDraft((current) => ({ ...current, ...patch }))
    test.reset()
  }

  function submit(event: FormEvent) {
    event.preventDefault()
    save.mutate({ ...draft, smtp_port: Number(draft.smtp_port) || 587 })
  }

  const ready = Boolean(settings?.smtp_host && settings.smtp_from_address)

  return (
    <form onSubmit={submit} className="flex flex-col gap-4">
      <Card className="flex flex-col gap-4">
        <div>
          <h2 className="text-lg font-semibold">{t('mail.serverSection')}</h2>
          <p className="mt-1 text-sm text-mist-500">{t('mail.intro')}</p>
        </div>
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
          <div className="sm:col-span-2">
            <Field label={t('mail.host')} value={draft.smtp_host} onChange={(event) => update({ smtp_host: event.target.value })} placeholder="smtp.example.com" autoComplete="off" />
          </div>
          <Field label={t('mail.port')} type="number" min={1} max={65535} value={draft.smtp_port} onChange={(event) => update({ smtp_port: event.target.value })} />
        </div>
        <label className="flex flex-col gap-1.5">
          <span className="text-sm font-medium text-mist-300">{t('mail.security')}</span>
          <select
            value={draft.smtp_security}
            onChange={(event) => {
              const security = event.target.value as Security
              const standardPort = Object.values(PORT_FOR).includes(draft.smtp_port)
              update({ smtp_security: security, ...(standardPort ? { smtp_port: PORT_FOR[security] } : {}) })
            }}
            className={SELECT_CLASS}
          >
            {SECURITIES.map((value) => (
              <option key={value} value={value}>
                {t(`mail.security_${value}`)}
              </option>
            ))}
          </select>
        </label>
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <Field label={t('mail.username')} value={draft.smtp_username} onChange={(event) => update({ smtp_username: event.target.value })} autoComplete="off" />
          <Field
            label={t('mail.password')}
            type="password"
            value={draft.smtp_password}
            onChange={(event) => update({ smtp_password: event.target.value })}
            placeholder={settings?.smtp_password_set ? settings.smtp_password : ''}
            hint={settings?.smtp_password_set ? t('common.secretSetHint') : undefined}
            autoComplete="new-password"
          />
        </div>
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <Field
            label={t('mail.fromAddress')}
            type="email"
            value={draft.smtp_from_address}
            onChange={(event) => update({ smtp_from_address: event.target.value })}
            placeholder="nexbeat@example.com"
            autoComplete="off"
          />
          <Field label={t('mail.fromName')} value={draft.smtp_from_name} onChange={(event) => update({ smtp_from_name: event.target.value })} autoComplete="off" />
        </div>
        <div className="flex flex-wrap items-center gap-3">
          <Button type="submit" loading={save.isPending}>
            {t('common.save')}
          </Button>
          <Button type="button" variant="ghost" onClick={() => test.mutate()} loading={test.isPending} disabled={!draft.smtp_host.trim()}>
            {t('mail.testConnection')}
          </Button>
          {test.isSuccess && <span className="text-sm text-ok-500">{t('mail.connectionOk')}</span>}
          {test.isError && <span className="text-sm text-bad-500">{errorMessage(test.error)}</span>}
        </div>
        {save.isError && <ErrorBanner message={errorMessage(save.error)} />}
        {save.isSuccess && <OkBanner message={t('common.saved')} />}
      </Card>

      <Card className="flex flex-col gap-4">
        <div>
          <h2 className="text-lg font-semibold">{t('mail.testSection')}</h2>
          <p className="mt-1 text-sm text-mist-500">{ready ? t('mail.testIntro', { email: user?.email }) : t('mail.testBlocked')}</p>
        </div>
        <div className="flex flex-wrap items-end gap-3">
          <div className="min-w-64 flex-1">
            <Field label={t('mail.recipient')} type="email" value={recipient} onChange={(event) => setRecipient(event.target.value)} placeholder={user?.email} autoComplete="off" />
          </div>
          <Button type="button" onClick={() => sendTest.mutate()} loading={sendTest.isPending} disabled={!ready} className="mb-0.5">
            {t('mail.sendTest')}
          </Button>
        </div>
        {sendTest.isSuccess && <OkBanner message={t('mail.testSent')} />}
        {sendTest.isError && <ErrorBanner message={errorMessage(sendTest.error)} />}
      </Card>
    </form>
  )
}
