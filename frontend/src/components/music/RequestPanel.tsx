import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router-dom'

import { api, errorMessage, storedError } from '../../api/client'
import type { AlbumPageData, CreatedRequest } from '../../api/types'
import { useAuth } from '../../auth/useAuth'
import { formatDate } from '../../lib/format'
import { Symbol } from '../Symbol'
import { Button, Card, ErrorBanner } from '../ui'

/**
 * Der Kasten, in dem angefragt wird. Er sagt vorher, was passiert: wie viel vom
 * Kontingent uebrig ist, ob ein Admin freigeben muss, ob Probelauf ist und ob
 * Lidarr diese Art Release ueberhaupt nimmt.
 */
export function RequestPanel({ data }: { data: AlbumPageData }) {
  const { t, i18n } = useTranslation()
  const { user, refreshUser } = useAuth()
  const queryClient = useQueryClient()
  const { album, library, request, quota } = data

  const create = useMutation({
    mutationFn: () => api.post<CreatedRequest>('/api/requests', { release_group_mbid: album.mbid }),
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['album', album.mbid] }),
        queryClient.invalidateQueries({ queryKey: ['artist', album.artist_mbid] }),
        queryClient.invalidateQueries({ queryKey: ['my-requests'] }),
        refreshUser(),
      ])
    },
  })
  // 12.09.2026: Eine sofort gescheiterte Anfrage zaehlt nicht, und danach stand wieder der
  // Knopf da. Ohne diese Meldung sah das aus, als sei nichts passiert.
  const failedNow = create.data?.request.status === 'failed' ? create.data.request : null

  let body
  if (library?.state === 'available' || request?.status === 'downloaded') {
    body = (
      <div className="flex items-start gap-3">
        <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-ok-500/15 text-ok-500">
          <Symbol name="check" className="h-5 w-5" />
        </span>
        <div>
          <p className="font-semibold">{t('request.available')}</p>
          <p className="mt-0.5 text-sm text-mist-500">{t('request.availableHint')}</p>
        </div>
      </div>
    )
  } else if (request) {
    const waiting = request.status === 'pending_approval'
    const dryRun = request.error_code === 'dry_run'
    const failed = request.status === 'failed'
    const progress = Math.max(library?.percent ?? 0, request.progress)
    body = (
      <div className="flex flex-col gap-3">
        <div className="flex items-start gap-3">
          <span
            className={
              'flex h-10 w-10 shrink-0 items-center justify-center rounded-full ' +
              (waiting || dryRun ? 'bg-warn-500/15 text-warn-500' : 'bg-accent-500/15 text-accent-400')
            }
          >
            <Symbol name="clock" className="h-5 w-5" />
          </span>
          <div>
            <p className="font-semibold">
              {waiting ? t('request.waiting') : dryRun ? t('request.dryRunSent') : failed ? t('request.failed') : t('request.searching')}
            </p>
            <p className="mt-0.5 text-sm text-mist-500">
              {request.mine ? t('request.byYou') : t('request.bySomeone')}
              {failed && request.error_code ? ` · ${storedError(request.error_code)}` : ''}
            </p>
          </div>
        </div>
        {!waiting && !dryRun && !failed && (
          <div>
            <div className="h-1.5 overflow-hidden rounded-full bg-ink-800">
              <div className="h-full rounded-full bg-accent-500 transition-[width]" style={{ width: `${Math.max(4, progress)}%` }} />
            </div>
            <p className="mt-1 text-xs text-mist-600 tabular-nums">{t('request.progress', { percent: progress })}</p>
          </div>
        )}
      </div>
    )
  } else if (!data.requests_enabled) {
    body = (
      <div className="flex flex-col gap-2">
        <p className="font-semibold">{t('request.notReady')}</p>
        <p className="text-sm text-mist-500">{user?.is_admin ? t('request.notReadyAdmin') : t('request.notReadyUser')}</p>
        {user?.is_admin && (
          <Link to="/admin/einstellungen?reiter=lidarr" className="text-sm font-semibold text-accent-500 hover:text-accent-400">
            {t('request.toSettings')}
          </Link>
        )}
      </div>
    )
  } else if (data.blocked) {
    // Liegt es am Profil des Kuenstlers in Lidarr, hilft die Auswahl in nexbeat nicht.
    const artistProfile = data.blocked === 'artist_profile_excludes_type'
    body = (
      <div className="flex flex-col gap-2">
        <p className="font-semibold">{t('request.blocked')}</p>
        <p className="text-sm text-mist-500">{storedError(data.blocked)}</p>
        {user?.is_admin && artistProfile && <p className="text-xs text-mist-600">{t('request.blockedArtistAdmin')}</p>}
        {user?.is_admin && !artistProfile && (
          <>
            <p className="text-xs text-mist-600">{t('request.blockedAdmin')}</p>
            <Link to="/admin/einstellungen?reiter=lidarr" className="text-sm font-semibold text-accent-500 hover:text-accent-400">
              {t('request.toSettings')}
            </Link>
          </>
        )}
      </div>
    )
  } else {
    const exhausted = quota.limit !== null && quota.used >= quota.limit
    body = (
      <div className="flex flex-col gap-4">
        <div>
          <p className="text-xs font-medium tracking-wide text-mist-600 uppercase">{t(`quota.period_${quota.period}`)}</p>
          <p className={'mt-0.5 text-2xl font-bold tabular-nums ' + (exhausted ? 'text-bad-500' : 'text-mist-100')}>
            {quota.limit === null ? t('quota.unlimited') : t('quota.remainingOf', { remaining: quota.remaining, limit: quota.limit })}
          </p>
          <p className="mt-0.5 text-xs text-mist-600">
            {exhausted
              ? t('quota.exhaustedUntil', { date: formatDate(quota.resets_at, i18n.language) })
              : t('quota.oneRequestOne')}
          </p>
        </div>
        {data.requires_approval && <p className="text-sm text-warn-500">{t('request.needsApproval')}</p>}
        {data.dry_run && user?.is_admin && (
          <p className="rounded-xl border border-warn-500/40 bg-warn-500/10 px-3 py-2 text-xs text-warn-500">{t('request.dryRunHint')}</p>
        )}
        <Button onClick={() => create.mutate()} loading={create.isPending} disabled={exhausted} className="w-full py-3 text-base">
          <Symbol name="inbox" className="h-5 w-5" />
          {t('request.submit')}
        </Button>
      </div>
    )
  }

  return (
    <Card className="flex flex-col gap-4">
      <h2 className="text-sm font-semibold tracking-wide text-mist-500 uppercase">{t('request.title')}</h2>
      {body}
      {create.isError && <ErrorBanner message={errorMessage(create.error)} />}
      {failedNow && (
        <ErrorBanner message={t('request.failedNow', { reason: storedError(failedNow.error_code) ?? '' }).trim()} />
      )}
    </Card>
  )
}
