import { useTranslation } from 'react-i18next'

import type { LibraryState, RequestState } from '../../api/types'
import { statusOf, type Tone } from './status'

const TONES: Record<Tone, string> = {
  ok: 'bg-ok-500/20 text-ok-500 ring-ok-500/40',
  warn: 'bg-warn-500/15 text-warn-500 ring-warn-500/40',
  bad: 'bg-bad-500/15 text-bad-500 ring-bad-500/40',
  accent: 'bg-accent-500/20 text-accent-400 ring-accent-500/40',
  muted: 'bg-ink-700/60 text-mist-300 ring-ink-600',
}

const DOT: Record<Tone, string> = {
  ok: 'bg-ok-500',
  warn: 'bg-warn-500',
  bad: 'bg-bad-500',
  accent: 'bg-accent-500',
  muted: 'bg-mist-500',
}

/** Das Schild zum Zustand. Auf einem Cover liegt es auf dem dunklen Schleier, damit es lesbar bleibt. */
export function StatusBadge({
  library,
  request,
  overImage = false,
}: {
  library?: LibraryState | null
  request?: RequestState | null
  overImage?: boolean
}) {
  const { t } = useTranslation()
  const status = statusOf(library, request)
  if (!status) return null
  return (
    <span
      className={
        'inline-flex items-center rounded-full px-2 py-0.5 text-[11px] font-semibold ring-1 ' +
        (overImage ? 'bg-scrim text-mist-100 ring-ink-700' : TONES[status.tone])
      }
    >
      {overImage && <span className={'mr-1.5 h-1.5 w-1.5 rounded-full ' + DOT[status.tone]} aria-hidden="true" />}
      {t(status.key)}
    </span>
  )
}
