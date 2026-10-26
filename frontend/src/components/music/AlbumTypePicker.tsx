import { useTranslation } from 'react-i18next'

import { ALBUM_TYPES } from '../../lib/albumTypes'
import { Symbol } from '../Symbol'

/**
 * Welche Arten von Alben ein ganzer Kuenstler bringt. Mehrere zugleich, mindestens eine: Die letzte laesst
 * sich nicht abwaehlen, sonst brachte die Anfrage nichts.
 */
export function AlbumTypePicker({
  value,
  onChange,
  label,
}: {
  value: readonly string[]
  onChange: (next: string[]) => void
  label: string
}) {
  const { t } = useTranslation()
  return (
    <div role="group" aria-label={label} className="flex flex-wrap gap-2">
      {ALBUM_TYPES.map((type) => {
        const on = value.includes(type)
        const last = on && value.length === 1
        return (
          <button
            key={type}
            type="button"
            aria-pressed={on}
            disabled={last}
            title={last ? t('albumTypes.atLeastOne') : undefined}
            onClick={() => onChange(on ? value.filter((item) => item !== type) : ALBUM_TYPES.filter((item) => item === type || value.includes(item)))}
            className={
              'inline-flex items-center gap-1.5 rounded-full border px-3 py-1.5 text-sm font-semibold transition-colors disabled:cursor-not-allowed ' +
              (on
                ? 'border-accent-600/60 bg-accent-700/20 text-accent-400'
                : 'border-ink-700 bg-ink-850 text-mist-500 hover:text-mist-300')
            }
          >
            {on && <Symbol name="check" className="h-3.5 w-3.5" />}
            {t(`albumTypes.${type}`)}
          </button>
        )
      })}
    </div>
  )
}
