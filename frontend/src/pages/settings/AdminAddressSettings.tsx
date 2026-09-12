import { useEffect, useRef, useState } from 'react'
import type { FormEvent } from 'react'
import { useTranslation } from 'react-i18next'

import { errorMessage } from '../../api/client'
import { Button, ErrorBanner, Field, OkBanner, PageLoading, Section, SELECT_CLASS } from '../../components/ui'
import { useSettings } from './useSettings'

export function AdminAddressSettings() {
  const { t } = useTranslation()
  const { query, settings, save } = useSettings()
  const [draft, setDraft] = useState({ public_url: '', default_language: 'de' })
  const filled = useRef(false)

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
          save.mutate(draft)
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
        {save.isError && <ErrorBanner message={errorMessage(save.error)} />}
        {save.isSuccess && <OkBanner message={t('common.saved')} />}
        <div>
          <Button type="submit" loading={save.isPending}>
            {t('common.save')}
          </Button>
        </div>
      </form>
    </Section>
  )
}
