import { useState } from 'react'
import type { FormEvent } from 'react'
import { useTranslation } from 'react-i18next'
import { Link, useSearchParams } from 'react-router-dom'

import { errorMessage } from '../api/client'
import { useAuth } from '../auth/useAuth'
import { AuthFrame } from '../components/AuthFrame'
import { ProviderButtons } from '../components/ProviderButtons'
import { Button, Card, ErrorBanner, Field } from '../components/ui'
import { oidcErrorKey } from '../vendor/nexoidc/oidc'

/**
 * Anmelden: Passwortformular, darunter "oder" und je aktivem Anbieter
 * ein Knopf. Ist die Anmeldung mit Passwort aus, stehen nur die Knoepfe da und klein der Weg des Betreibers.
 */
export function LoginPage() {
  const { t } = useTranslation()
  const { login, config } = useAuth()
  const [name, setName] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [operator, setOperator] = useState(false)
  // Ein gescheiterter Ruecksprung vom Anbieter landet hier, mit der Kennung in der Adresse. Nur bekannte Kennungen
  // werden zum Satz, nie der rohe Wert aus der Adresse.
  const [params] = useSearchParams()
  const returnKey = oidcErrorKey(params.get('error'))
  const providers = config?.oidc_providers ?? []
  const withPassword = config?.password_login !== false || providers.length === 0 || operator

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

  const problem = error ?? (returnKey ? t(returnKey) : null)

  return (
    <AuthFrame>
      <Card>
        <h1 className="text-2xl font-bold tracking-tight">{t('login.title')}</h1>
        <p className="mt-1.5 text-sm text-mist-500">{t('app.tagline')}</p>
        <div className="mt-6 flex flex-col gap-4">
          {problem && <ErrorBanner message={problem} />}
          {withPassword && (
            <form onSubmit={submit} className="flex flex-col gap-4">
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
              <Button type="submit" loading={busy} className="mt-1 w-full">
                {t('login.submit')}
              </Button>
            </form>
          )}
          <ProviderButtons providers={providers} separator={withPassword} />
          {!withPassword && (
            <button
              type="button"
              onClick={() => setOperator(true)}
              className="text-center text-xs text-mist-600 underline-offset-2 hover:text-mist-300 hover:underline"
            >
              {t('oidc.login.operator')}
            </button>
          )}
          {withPassword && config?.mail_configured && (
            <Link
              to="/passwort-vergessen"
              className="text-center text-xs text-mist-600 underline-offset-2 hover:text-mist-300 hover:underline"
            >
              {t('login.forgot')}
            </Link>
          )}
        </div>
      </Card>
    </AuthFrame>
  )
}
