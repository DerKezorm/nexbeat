import { useState } from 'react'
import type { FormEvent } from 'react'
import { useTranslation } from 'react-i18next'
import { Link, useSearchParams } from 'react-router-dom'

import { errorMessage, storedError } from '../api/client'
import { useAuth } from '../auth/useAuth'
import { AuthFrame } from '../components/AuthFrame'
import { Button, Card, ErrorBanner, Field } from '../components/ui'

export function LoginPage() {
  const { t } = useTranslation()
  const { login, config } = useAuth()
  const [name, setName] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  // Ein gescheiterter Ruecksprung vom Anmeldeanbieter landet hier, mit der Kennung in der Adresse.
  const [params] = useSearchParams()
  const oidcError = storedError(params.get('oidc_error'))
  const providers = config?.oidc_providers ?? []

  async function submit(event: FormEvent) {
    event.preventDefault()
    if (busy) return
    setError(null)
    setBusy(true)
    try {
      await login(name.trim(), password)
    } catch (caught) {
      setError(errorMessage(caught))
    } finally {
      setBusy(false)
    }
  }

  return (
    <AuthFrame>
      <Card>
        <h1 className="text-2xl font-bold tracking-tight">{t('login.title')}</h1>
        <p className="mt-1.5 text-sm text-mist-500">{t('app.tagline')}</p>
        <form onSubmit={submit} className="mt-6 flex flex-col gap-4">
          <Field
            label={t('login.nameLabel')}
            value={name}
            onChange={(event) => setName(event.target.value)}
            autoComplete="username"
            required
            autoFocus
          />
          <Field
            label={t('login.passwordLabel')}
            type="password"
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            autoComplete="current-password"
            required
          />
          {(error || oidcError) && <ErrorBanner message={error ?? oidcError ?? ''} />}
          <Button type="submit" loading={busy} className="mt-1 w-full">
            {t('login.submit')}
          </Button>
          {providers.length > 0 && (
            <div className="flex flex-col gap-2">
              <div className="flex items-center gap-3 text-xs text-mist-600">
                <span className="h-px flex-1 bg-ink-700" />
                {t('login.oidcOr')}
                <span className="h-px flex-1 bg-ink-700" />
              </div>
              {providers.map((provider) => (
                // Ein echter Link, kein fetch: Der Anbieter braucht den ganzen Browser, und das Cookie des
                // Versuchs kommt mit der Weiterleitung.
                <a
                  key={provider.slug}
                  href={`/api/auth/oidc/${encodeURIComponent(provider.slug)}/login`}
                  className="inline-flex w-full items-center justify-center rounded-full border border-ink-700 bg-ink-850 px-5 py-2.5 text-sm font-semibold text-mist-300 transition-colors hover:bg-ink-800 hover:text-mist-100"
                >
                  {t('login.oidcWith', { label: provider.label })}
                </a>
              ))}
            </div>
          )}
          {config?.mail_configured && (
            <Link
              to="/passwort-vergessen"
              className="text-center text-xs text-mist-600 underline-offset-2 hover:text-mist-300 hover:underline"
            >
              {t('login.forgot')}
            </Link>
          )}
        </form>
      </Card>
    </AuthFrame>
  )
}
