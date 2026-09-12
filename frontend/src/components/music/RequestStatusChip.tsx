import { useTranslation } from 'react-i18next'

import type { MusicRequest } from '../../api/types'

const TONE: Record<string, string> = {
  pending_approval: 'bg-warn-500/15 text-warn-500 ring-warn-500/40',
  approved: 'bg-accent-500/15 text-accent-400 ring-accent-500/40',
  searching: 'bg-accent-500/15 text-accent-400 ring-accent-500/40',
  downloaded: 'bg-ok-500/15 text-ok-500 ring-ok-500/40',
  rejected: 'bg-ink-700/60 text-mist-400 ring-ink-600',
  failed: 'bg-bad-500/15 text-bad-500 ring-bad-500/40',
  cancelled: 'bg-ink-700/60 text-mist-400 ring-ink-600',
  dry_run: 'bg-warn-500/15 text-warn-500 ring-warn-500/40',
}

/** Der Stand einer Anfrage als Schild. Probelauf ist ein eigener Fall, damit er nicht wie "unterwegs" aussieht. */
export function RequestStatusChip({ request }: { request: Pick<MusicRequest, 'status' | 'error_code'> }) {
  const { t } = useTranslation()
  const key = request.status === 'approved' && request.error_code === 'dry_run' ? 'dry_run' : request.status
  return (
    <span className={'inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-semibold ring-1 ' + TONE[key]}>
      {t(`requestStatus.${key}`)}
    </span>
  )
}
