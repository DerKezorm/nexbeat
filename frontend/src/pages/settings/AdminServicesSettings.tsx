import { useState } from 'react'
import { useTranslation } from 'react-i18next'

import { errorMessage } from '../../api/client'
import { useAuth } from '../../auth/useAuth'
import { ErrorBanner, PageLoading, Section } from '../../components/ui'
import { AdminLidarrSettings } from './AdminLidarrSettings'
import { AdminNexcrateSettings } from './AdminNexcrateSettings'
import { useSettings } from './useSettings'

type Mode = 'arr' | 'nex'

/**
 * Wohin Anfragen gehen: ARR-Modus (Lidarr) oder NEX-Modus (nexcrate), entschieden am 22.09.2026.
 * Genau eins; darunter steht nur der Teil des gewaehlten Programms.
 *
 * Eine Installation, die vor dem Modus schon Lidarr eingetragen hatte, gilt als ARR-Modus, ohne
 * dass jemand etwas waehlen muss.
 */
export function AdminServicesSettings() {
  const { t } = useTranslation()
  const { refreshUser } = useAuth()
  const { query, settings, save } = useSettings()
  const [switched, setSwitched] = useState(false)

  if (query.isPending || !settings) return <PageLoading />

  const chosen = settings.request_mode || (settings.lidarr_url && settings.lidarr_api_key_set ? 'arr' : '')

  function choose(next: Mode) {
    if (next === chosen) return
    save.mutate(
      { request_mode: next },
      {
        onSuccess: () => {
          setSwitched(chosen !== '')
          // Die Texte nennen das Ziel ("nexcrate sucht"), und das steht am Konto.
          void refreshUser()
        },
      },
    )
  }

  const options: { value: Mode; title: string; text: string }[] = [
    { value: 'arr', title: t('services.arr'), text: t('services.arrText') },
    { value: 'nex', title: t('services.nex'), text: t('services.nexText') },
  ]

  return (
    <div className="flex flex-col gap-4">
      <Section title={t('services.modeTitle')} intro={t('services.modeIntro')}>
        <div role="radiogroup" aria-label={t('services.modeTitle')} className="grid gap-3 sm:grid-cols-2">
          {options.map((option) => {
            const active = chosen === option.value
            return (
              <button
                key={option.value}
                type="button"
                role="radio"
                aria-checked={active}
                disabled={save.isPending}
                onClick={() => choose(option.value)}
                className={
                  'rounded-xl border p-4 text-left transition-colors ' +
                  (active ? 'border-accent-500 bg-accent-500/10' : 'border-ink-700 hover:bg-ink-800')
                }
              >
                <span className="block font-semibold">{option.title}</span>
                <span className="mt-1 block text-sm text-mist-400">{option.text}</span>
              </button>
            )
          })}
        </div>
        {!chosen && <p className="text-sm text-mist-500">{t('services.none')}</p>}
        {switched && (
          <p role="note" className="rounded-xl border border-warn-500/40 bg-warn-500/10 px-4 py-3 text-sm text-warn-500">
            {t('services.switchNote')}
          </p>
        )}
        {save.isError && <ErrorBanner message={errorMessage(save.error)} />}
      </Section>

      {chosen === 'arr' && <AdminLidarrSettings />}
      {chosen === 'nex' && <AdminNexcrateSettings />}
    </div>
  )
}
