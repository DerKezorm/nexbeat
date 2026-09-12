import { useState } from 'react'
import type { FormEvent } from 'react'
import { useMutation } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'

import { api, errorMessage, type TokenPair } from '../api/client'
import type { Me } from '../api/types'
import { useAuth } from '../auth/useAuth'
import { Button, ErrorBanner, Field, OkBanner, PageTitle, Section, SELECT_CLASS } from '../components/ui'
import { changeLanguage, isLanguage } from '../i18n'
import { formatDate } from '../lib/format'

export function ProfilePage() {
  const { t, i18n } = useTranslation()
  const { user, updateUser, startSession } = useAuth()
  const [displayName, setDisplayName] = useState(user?.display_name ?? '')
  const [language, setLanguage] = useState<string>(user?.language ?? '')
  const [passwords, setPasswords] = useState({ current: '', next: '' })

  const saveAccount = useMutation({
    mutationFn: () => api.patch<Me>('/api/auth/me', { display_name: displayName, language }),
    onSuccess: async (me) => {
      updateUser(me)
      if (isLanguage(me.language)) await changeLanguage(me.language)
    },
  })
  const changePassword = useMutation({
    mutationFn: () =>
      api.post<TokenPair>('/api/auth/me/password', { current_password: passwords.current, new_password: passwords.next }),
    onSuccess: async (tokens) => {
      await startSession(tokens)
      setPasswords({ current: '', next: '' })
    },
  })

  if (!user) return null

  return (
    <div className="flex flex-col gap-6">
      <PageTitle>{t('profile.title')}</PageTitle>

      <Section title={t('profile.account')} intro={t('profile.accountIntro', { username: user.username, email: user.email })}>
        <form
          className="flex flex-col gap-4"
          onSubmit={(event: FormEvent) => {
            event.preventDefault()
            saveAccount.mutate()
          }}
        >
          <div className="grid gap-4 sm:grid-cols-2">
            <Field label={t('profile.displayName')} value={displayName} onChange={(event) => setDisplayName(event.target.value)} maxLength={128} />
            <label className="flex flex-col gap-1.5">
              <span className="text-sm font-medium text-mist-300">{t('profile.language')}</span>
              <select value={language} onChange={(event) => setLanguage(event.target.value)} className={SELECT_CLASS}>
                <option value="">{t('profile.languageDefault')}</option>
                <option value="de">Deutsch</option>
                <option value="en">English</option>
              </select>
            </label>
          </div>
          {saveAccount.isError && <ErrorBanner message={errorMessage(saveAccount.error)} />}
          {saveAccount.isSuccess && <OkBanner message={t('common.saved')} />}
          <div>
            <Button type="submit" loading={saveAccount.isPending}>
              {t('common.save')}
            </Button>
          </div>
        </form>
      </Section>

      <Section title={t('profile.password')} intro={t('profile.passwordIntro')}>
        <form
          className="flex flex-col gap-4"
          onSubmit={(event: FormEvent) => {
            event.preventDefault()
            changePassword.mutate()
          }}
        >
          <div className="grid gap-4 sm:grid-cols-2">
            <Field
              label={t('profile.currentPassword')}
              type="password"
              value={passwords.current}
              onChange={(event) => setPasswords({ ...passwords, current: event.target.value })}
              autoComplete="current-password"
              required
            />
            <Field
              label={t('profile.newPassword')}
              type="password"
              value={passwords.next}
              onChange={(event) => setPasswords({ ...passwords, next: event.target.value })}
              hint={t('common.passwordHint')}
              autoComplete="new-password"
              minLength={8}
              required
            />
          </div>
          {changePassword.isError && <ErrorBanner message={errorMessage(changePassword.error)} />}
          {changePassword.isSuccess && <OkBanner message={t('profile.passwordChanged')} />}
          <div>
            <Button type="submit" loading={changePassword.isPending}>
              {t('profile.changePassword')}
            </Button>
          </div>
        </form>
      </Section>

      <Section title={t('profile.quota')}>
        <p className="text-sm text-mist-300">
          {user.quota.limit === null
            ? t('quota.unlimited')
            : t('profile.quotaText', {
                used: user.quota.used,
                limit: user.quota.limit,
                period: t(`quota.period_${user.quota.period}`),
                date: formatDate(user.quota.resets_at, i18n.language),
              })}
        </p>
        {user.requires_approval && <p className="text-sm text-warn-500">{t('request.needsApproval')}</p>}
      </Section>
    </div>
  )
}
