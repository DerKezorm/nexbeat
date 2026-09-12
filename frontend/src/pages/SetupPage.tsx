import { useState } from 'react'
import type { FormEvent } from 'react'
import { useTranslation } from 'react-i18next'

import { api, errorMessage, type TokenPair } from '../api/client'
import { useAuth } from '../auth/useAuth'
import { AuthFrame } from '../components/AuthFrame'
import { Button, Card, ErrorBanner, Field, SELECT_CLASS } from '../components/ui'
import { changeLanguage, isLanguage, type Language } from '../i18n'

/** Erst-Einrichtung: Das erste Konto wird Admin. */
export function SetupPage() {
  const { t, i18n } = useTranslation()
  const { startSession } = useAuth()
  const [form, setForm] = useState({ username: '', email: '', password: '' })
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const language: Language = isLanguage(i18n.language) ? i18n.language : 'de'

  async function submit(event: FormEvent) {
    event.preventDefault()
    setError(null)
    setBusy(true)
    try {
      const tokens = await api.post<TokenPair>('/api/setup/admin', { ...form, language }, { auth: false })
      await startSession(tokens)
    } catch (caught) {
      setError(errorMessage(caught))
    } finally {
      setBusy(false)
    }
  }

  return (
    <AuthFrame wide>
      <Card>
        <h1 className="text-2xl font-bold tracking-tight">
          {t('setup.title')}
          <span className="text-accent-500">.</span>
        </h1>
        <p className="mt-1.5 text-sm text-mist-500">{t('setup.intro')}</p>
        <form onSubmit={submit} className="mt-6 flex flex-col gap-4">
          <Field
            label={t('setup.username')}
            value={form.username}
            onChange={(event) => setForm({ ...form, username: event.target.value })}
            hint={t('setup.usernameHint')}
            autoComplete="username"
            required
            autoFocus
          />
          <Field
            label={t('setup.email')}
            type="email"
            value={form.email}
            onChange={(event) => setForm({ ...form, email: event.target.value })}
            autoComplete="email"
            required
          />
          <Field
            label={t('setup.password')}
            type="password"
            value={form.password}
            onChange={(event) => setForm({ ...form, password: event.target.value })}
            hint={t('common.passwordHint')}
            autoComplete="new-password"
            minLength={8}
            required
          />
          <label className="flex flex-col gap-1.5">
            <span className="text-sm font-medium text-mist-300">{t('setup.language')}</span>
            <select value={language} onChange={(event) => void changeLanguage(event.target.value as Language)} className={SELECT_CLASS}>
              <option value="de">Deutsch</option>
              <option value="en">English</option>
            </select>
          </label>
          {error && <ErrorBanner message={error} />}
          <Button type="submit" loading={busy} className="mt-1 w-full">
            {t('setup.submit')}
          </Button>
        </form>
      </Card>
    </AuthFrame>
  )
}
