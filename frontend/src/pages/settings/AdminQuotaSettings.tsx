import { useEffect, useRef, useState } from 'react'
import type { FormEvent } from 'react'
import { useTranslation } from 'react-i18next'

import { errorMessage } from '../../api/client'
import { Button, ErrorBanner, Field, OkBanner, PageLoading, Section, SELECT_CLASS } from '../../components/ui'
import { useSettings } from './useSettings'

/** Die Vorgabe fuer alle Konten. Einzelne Konten weichen unter "Benutzer" ab. */
export function AdminQuotaSettings() {
  const { t } = useTranslation()
  const { query, settings, save } = useSettings()
  const filled = useRef(false)
  const [limit, setLimit] = useState('')
  const [period, setPeriod] = useState<'day' | 'week' | 'month'>('week')

  useEffect(() => {
    if (!settings || filled.current) return
    filled.current = true
    setLimit(settings.quota_default_limit === null ? '' : String(settings.quota_default_limit))
    setPeriod(settings.quota_period)
  }, [settings])

  if (query.isPending) return <PageLoading />

  function submit(event: FormEvent) {
    event.preventDefault()
    // Leer heisst unbegrenzt, der Server nimmt dafuer -1.
    save.mutate({ quota_default_limit: limit.trim() === '' ? -1 : Number(limit), quota_period: period })
  }

  return (
    <Section title={t('quota.title')} intro={t('quota.intro')}>
      <form onSubmit={submit} className="flex flex-col gap-4">
        <div className="grid gap-4 sm:grid-cols-2">
          <Field
            label={t('quota.defaultLimit')}
            type="number"
            min={0}
            max={10000}
            value={limit}
            onChange={(event) => setLimit(event.target.value)}
            placeholder="∞"
            hint={t('quota.defaultLimitHint')}
          />
          <label className="flex flex-col gap-1.5">
            <span className="text-sm font-medium text-mist-300">{t('quota.period')}</span>
            <select value={period} onChange={(event) => setPeriod(event.target.value as typeof period)} className={SELECT_CLASS}>
              <option value="day">{t('quota.everyDay')}</option>
              <option value="week">{t('quota.everyWeek')}</option>
              <option value="month">{t('quota.everyMonth')}</option>
            </select>
            <span className="text-xs text-mist-500">{t('quota.periodHint')}</span>
          </label>
        </div>
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
