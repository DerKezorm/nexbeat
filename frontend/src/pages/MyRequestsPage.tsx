import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router-dom'

import { api, errorMessage, storedError } from '../api/client'
import type { MusicRequest } from '../api/types'
import { useAuth } from '../auth/useAuth'
import { ArtistImage } from '../components/music/ArtistImage'
import { Cover } from '../components/music/Cover'
import { RequestStatusChip } from '../components/music/RequestStatusChip'
import { Symbol } from '../components/Symbol'
import { Button, ErrorBanner, KeyFigure, PageLoading, PageTitle } from '../components/ui'
import { formatDate } from '../lib/format'

export function MyRequestsPage() {
  const { t, i18n } = useTranslation()
  const { user, refreshUser } = useAuth()
  const queryClient = useQueryClient()
  const query = useQuery({
    queryKey: ['my-requests'],
    queryFn: () => api.get<MusicRequest[]>('/api/requests/mine'),
    refetchInterval: 60_000,
  })
  const cancel = useMutation({
    mutationFn: (id: number) => api.post<MusicRequest>(`/api/requests/${id}/cancel`),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['my-requests'] })
      await refreshUser()
    },
  })

  const quota = user?.quota
  const requests = query.data ?? []
  const open = requests.filter((request) => ['pending_approval', 'approved', 'searching'].includes(request.status)).length
  const done = requests.filter((request) => request.status === 'downloaded').length

  return (
    <div className="flex flex-col gap-8">
      <PageTitle sub={t('myRequests.intro')}>{t('myRequests.title')}</PageTitle>

      {quota && (
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          <KeyFigure
            label={t(`quota.period_${quota.period}`)}
            value={quota.limit === null ? '∞' : `${quota.used}/${quota.limit}`}
            hint={quota.limit === null ? t('quota.unlimited') : t('quota.resetsOn', { date: formatDate(quota.resets_at, i18n.language) })}
          />
          <KeyFigure label={t('myRequests.open')} value={String(open)} />
          <KeyFigure label={t('myRequests.done')} value={String(done)} />
          <KeyFigure label={t('myRequests.total')} value={String(requests.length)} />
        </div>
      )}

      {cancel.isError && <ErrorBanner message={errorMessage(cancel.error)} />}
      {query.isPending && <PageLoading />}
      {query.isError && <ErrorBanner message={errorMessage(query.error)} />}

      {query.isSuccess && requests.length === 0 && (
        <div className="flex flex-col items-center gap-3 rounded-2xl border border-dashed border-ink-700 px-6 py-14 text-center">
          <Symbol name="inbox" className="h-8 w-8 text-accent-500" />
          <p className="max-w-md text-sm text-mist-500">{t('myRequests.empty')}</p>
          <Link to="/" className="rounded-full bg-accent-500 px-5 py-2.5 text-sm font-semibold text-white hover:bg-accent-400">
            {t('myRequests.toDiscover')}
          </Link>
        </div>
      )}

      <ul className="grid gap-3 lg:grid-cols-2">
        {requests.map((request) => {
          const cancellable = request.status === 'pending_approval' || (request.status === 'approved' && request.error_code === 'dry_run')
          const errorText = request.status === 'failed' ? storedError(request.error_code) : null
          const wholeArtist = request.kind === 'artist'
          const target = wholeArtist ? `/kuenstler/${request.artist_mbid}` : `/album/${request.release_group_mbid}`
          return (
            <li key={request.id} className="flex gap-4 rounded-2xl border border-ink-700 bg-ink-850/80 p-3">
              <Link to={target} className="shrink-0">
                {wholeArtist ? (
                  <ArtistImage src={request.cover_url} name={request.artist_name} className="h-20 w-20 rounded-full border border-ink-700" />
                ) : (
                  <Cover src={request.cover_url} alt="" className="h-20 w-20 rounded-xl border border-ink-700" />
                )}
              </Link>
              <div className="flex min-w-0 flex-1 flex-col gap-1">
                <div className="flex items-start justify-between gap-2">
                  <div className="min-w-0">
                    <Link to={target} className="line-clamp-1 font-semibold hover:text-accent-400">
                      {request.title}
                    </Link>
                    {wholeArtist ? (
                      <p className="line-clamp-1 text-sm text-mist-400">{t('artistRequest.kind')}</p>
                    ) : (
                      <Link to={`/kuenstler/${request.artist_mbid}`} className="line-clamp-1 text-sm text-mist-400 hover:text-mist-200">
                        {request.artist_name}
                      </Link>
                    )}
                  </div>
                  <RequestStatusChip request={request} />
                </div>
                {request.status === 'searching' && (
                  <div className="mt-1 h-1.5 overflow-hidden rounded-full bg-ink-800">
                    <div className="h-full rounded-full bg-accent-500" style={{ width: `${Math.max(4, request.progress)}%` }} />
                  </div>
                )}
                {errorText && <p className="text-xs text-bad-500">{errorText}</p>}
                {request.rejection_reason && <p className="text-xs text-mist-500">„{request.rejection_reason}“</p>}
                <div className="mt-auto flex items-center justify-between gap-2 pt-1">
                  <span className="text-xs text-mist-600">{formatDate(request.requested_at, i18n.language)}</span>
                  {cancellable && (
                    <Button variant="ghost" className="px-3 py-1 text-xs" loading={cancel.isPending && cancel.variables === request.id} onClick={() => cancel.mutate(request.id)}>
                      {t('myRequests.cancel')}
                    </Button>
                  )}
                </div>
              </div>
            </li>
          )
        })}
      </ul>
    </div>
  )
}
