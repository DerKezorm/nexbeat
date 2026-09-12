import type { LibraryState, RequestState } from '../../api/types'

export type Tone = 'ok' | 'warn' | 'bad' | 'accent' | 'muted'

/** Was ueber ein Release zu sagen ist. Der Bestand schlaegt die Anfrage. */
export function statusOf(
  library: LibraryState | null | undefined,
  request: RequestState | null | undefined,
): { key: string; tone: Tone } | null {
  if (library?.state === 'available') return { key: 'status.available', tone: 'ok' }
  if (request?.status === 'downloaded') return { key: 'status.available', tone: 'ok' }
  if (library?.state === 'partial') return { key: 'status.partial', tone: 'warn' }
  if (request) {
    if (request.status === 'pending_approval') return { key: 'status.pendingApproval', tone: 'warn' }
    if (request.status === 'approved' && request.error_code === 'dry_run') return { key: 'status.dryRun', tone: 'warn' }
    if (request.status === 'approved' || request.status === 'searching') return { key: 'status.searching', tone: 'accent' }
  }
  if (library?.state === 'wanted') return { key: 'status.wanted', tone: 'accent' }
  return null
}
