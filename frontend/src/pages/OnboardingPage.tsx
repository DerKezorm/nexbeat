import { useState } from 'react'
import type { FormEvent } from 'react'
import { useMutation, useQuery } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { Link, useParams } from 'react-router-dom'

import { api, errorMessage } from '../api/client'
import { AuthFrame } from '../components/AuthFrame'
import { Button, Card, ErrorBanner, Field, OkBanner, PageLoading } from '../components/ui'

function BackToLogin() {
  const { t } = useTranslation()
  return (
    <Link to="/" className="mt-4 inline-block text-sm font-semibold text-accent-500 hover:text-accent-400">
      {t('onboarding.toLogin')}
    </Link>
  )
}

/** Einladung annehmen: Name und Passwort waehlen. Danach geht es zur normalen Anmeldung. */
export function InvitationPage() {
  const { t } = useTranslation()
  const { token = '' } = useParams()
  const [form, setForm] = useState({ username: '', display_name: '', password: '' })

  const info = useQuery({
    queryKey: ['invitation', token],
    queryFn: () => api.get<{ email: string; role: string }>(`/api/onboarding/invitation/${token}`, { auth: false }),
    retry: false,
  })

  const accept = useMutation({
    mutationFn: () => api.post<{ username: string }>(`/api/onboarding/invitation/${token}`, form, { auth: false }),
  })

  function submit(event: FormEvent) {
    event.preventDefault()
    accept.mutate()
  }

  return (
    <AuthFrame wide>
      <Card>
        {info.isPending ? (
          <PageLoading />
        ) : info.isError ? (
          <>
            <h1 className="text-2xl font-bold tracking-tight">{t('onboarding.invitationTitle')}</h1>
            <div className="mt-4">
              <ErrorBanner message={errorMessage(info.error)} />
            </div>
            <BackToLogin />
          </>
        ) : accept.isSuccess ? (
          <>
            <h1 className="text-2xl font-bold tracking-tight">{t('onboarding.accountCreated')}</h1>
            <p className="mt-2 text-sm text-mist-400">{t('onboarding.accountCreatedHint', { username: accept.data.username })}</p>
            <BackToLogin />
          </>
        ) : (
          <>
            <h1 className="text-2xl font-bold tracking-tight">
              {t('onboarding.invitationTitle')}
              <span className="text-accent-500">.</span>
            </h1>
            <p className="mt-1.5 text-sm text-mist-500">{t('onboarding.invitationIntro', { email: info.data.email })}</p>
            <form onSubmit={submit} className="mt-6 flex flex-col gap-4">
              <Field
                label={t('onboarding.username')}
                value={form.username}
                onChange={(event) => setForm({ ...form, username: event.target.value })}
                hint={t('setup.usernameHint')}
                autoComplete="username"
                required
                autoFocus
              />
              <Field
                label={t('onboarding.displayName')}
                value={form.display_name}
                onChange={(event) => setForm({ ...form, display_name: event.target.value })}
                autoComplete="name"
              />
              <Field
                label={t('onboarding.password')}
                type="password"
                value={form.password}
                onChange={(event) => setForm({ ...form, password: event.target.value })}
                hint={t('common.passwordHint')}
                autoComplete="new-password"
                minLength={8}
                required
              />
              {accept.isError && <ErrorBanner message={errorMessage(accept.error)} />}
              <Button type="submit" loading={accept.isPending} className="mt-1 w-full">
                {t('onboarding.createAccount')}
              </Button>
            </form>
          </>
        )}
      </Card>
    </AuthFrame>
  )
}

/** Neues Passwort ueber den Link aus der Mail. */
export function SetPasswordPage() {
  const { t } = useTranslation()
  const { token = '' } = useParams()
  const [password, setPassword] = useState('')
  const [repeat, setRepeat] = useState('')

  const check = useQuery({
    queryKey: ['reset', token],
    queryFn: () => api.get<{ valid: boolean }>(`/api/onboarding/password/${token}`, { auth: false }),
    retry: false,
  })
  const save = useMutation({
    mutationFn: () => api.post<void>(`/api/onboarding/password/${token}`, { password }, { auth: false }),
  })
  const mismatch = repeat.length > 0 && repeat !== password

  function submit(event: FormEvent) {
    event.preventDefault()
    if (!mismatch) save.mutate()
  }

  return (
    <AuthFrame>
      <Card>
        <h1 className="text-2xl font-bold tracking-tight">{t('onboarding.resetTitle')}</h1>
        {check.isPending ? (
          <PageLoading />
        ) : check.isError ? (
          <div className="mt-4">
            <ErrorBanner message={errorMessage(check.error)} />
            <BackToLogin />
          </div>
        ) : save.isSuccess ? (
          <div className="mt-4">
            <OkBanner message={t('onboarding.resetDone')} />
            <BackToLogin />
          </div>
        ) : (
          <form onSubmit={submit} className="mt-6 flex flex-col gap-4">
            <Field
              label={t('onboarding.newPassword')}
              type="password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              hint={t('common.passwordHint')}
              autoComplete="new-password"
              minLength={8}
              required
              autoFocus
            />
            <Field
              label={t('onboarding.repeatPassword')}
              type="password"
              value={repeat}
              onChange={(event) => setRepeat(event.target.value)}
              autoComplete="new-password"
              required
            />
            {mismatch && <ErrorBanner message={t('onboarding.mismatch')} />}
            {save.isError && <ErrorBanner message={errorMessage(save.error)} />}
            <Button type="submit" loading={save.isPending} disabled={mismatch} className="mt-1 w-full">
              {t('onboarding.savePassword')}
            </Button>
          </form>
        )}
      </Card>
    </AuthFrame>
  )
}

/** Passwort vergessen. Die Antwort ist immer dieselbe, egal ob es die Adresse gibt. */
export function ForgotPasswordPage() {
  const { t } = useTranslation()
  const [email, setEmail] = useState('')
  const send = useMutation({
    mutationFn: () => api.post<{ status: string }>('/api/onboarding/forgot-password', { email }, { auth: false }),
  })

  return (
    <AuthFrame>
      <Card>
        <h1 className="text-2xl font-bold tracking-tight">{t('onboarding.forgotTitle')}</h1>
        <p className="mt-1.5 text-sm text-mist-500">{t('onboarding.forgotIntro')}</p>
        {send.isSuccess ? (
          <div className="mt-4">
            <OkBanner message={t('onboarding.forgotSent')} />
            <BackToLogin />
          </div>
        ) : (
          <form
            onSubmit={(event) => {
              event.preventDefault()
              send.mutate()
            }}
            className="mt-6 flex flex-col gap-4"
          >
            <Field
              label={t('setup.email')}
              type="email"
              value={email}
              onChange={(event) => setEmail(event.target.value)}
              autoComplete="email"
              required
              autoFocus
            />
            {send.isError && <ErrorBanner message={errorMessage(send.error)} />}
            <Button type="submit" loading={send.isPending} className="w-full">
              {t('onboarding.sendLink')}
            </Button>
            <BackToLogin />
          </form>
        )}
      </Card>
    </AuthFrame>
  )
}
