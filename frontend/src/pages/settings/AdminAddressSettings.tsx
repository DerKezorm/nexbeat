import { useEffect, useRef, useState } from 'react'
import type { FormEvent } from 'react'
import { useTranslation } from 'react-i18next'

import { errorMessage } from '../../api/client'
import { ConfirmDialog } from '../../components/ConfirmDialog'
import { Button, ErrorBanner, Field, OkBanner, PageLoading, Section, SELECT_CLASS } from '../../components/ui'
import { AddressQuestion } from '../../components/AddressQuestion'
import { questionOf, type AddressQuestionValues } from '../../lib/addressQuestion'
import { useSettings } from './useSettings'

export function AdminAddressSettings() {
  const { t } = useTranslation()
  const { query, settings, save } = useSettings()
  const [draft, setDraft] = useState({ public_url: '', default_language: 'de' })
  const filled = useRef(false)
  // Dieselbe Rueckfrage wie unter Anmeldung: Kennt ein Anbieter die bisherige Adresse, fragt
  // der Server, bevor er speichert.
  const [question, setQuestion] = useState<AddressQuestionValues | null>(null)
  const submit = (confirm: boolean) => {
    setQuestion(null)
    save.mutate(confirm ? { ...draft, confirm_address: true } : draft, { onError: (error) => setQuestion(questionOf(error)) })
  }

  // Nur einmal vorbelegen, sonst setzt ein Hintergrund-Abgleich mitten im Tippen zurueck.
  useEffect(() => {
    if (!settings || filled.current) return
    filled.current = true
    setDraft({ public_url: settings.public_url, default_language: settings.default_language })
  }, [settings])

  if (query.isPending) return <PageLoading />

  return (
    <Section title={t('address.title')} intro={t('address.intro')}>
      <form
        className="flex flex-col gap-4"
        onSubmit={(event: FormEvent) => {
          event.preventDefault()
          submit(false)
        }}
      >
        <Field
          label={t('address.publicUrl')}
          value={draft.public_url}
          onChange={(event) => setDraft({ ...draft, public_url: event.target.value })}
          placeholder="https://music.example.com"
          hint={t('address.publicUrlHint')}
        />
        <label className="flex flex-col gap-1.5">
          <span className="text-sm font-medium text-mist-300">{t('address.language')}</span>
          <select
            value={draft.default_language}
            onChange={(event) => setDraft({ ...draft, default_language: event.target.value })}
            className={SELECT_CLASS}
          >
            <option value="de">Deutsch</option>
            <option value="en">English</option>
          </select>
          <span className="text-xs text-mist-500">{t('address.languageHint')}</span>
        </label>
        {save.isError && questionOf(save.error) === null && <ErrorBanner message={errorMessage(save.error)} />}
        {save.isSuccess && <OkBanner message={t('common.saved')} />}
        <div>
          <Button type="submit" loading={save.isPending}>
            {t('common.save')}
          </Button>
        </div>
      </form>
      <ConfirmDialog
        open={question !== null}
        title={t('oidc.admin.address')}
        description={question ? <AddressQuestion question={question} /> : null}
        confirmLabel={t('common.save')}
        loading={save.isPending}
        onCancel={() => setQuestion(null)}
        onConfirm={() => submit(true)}
      />
    </Section>
  )
}
