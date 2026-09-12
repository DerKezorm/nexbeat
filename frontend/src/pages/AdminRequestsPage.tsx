import { useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router-dom'

import { api, errorMessage, storedError } from '../api/client'
import type { MusicRequest } from '../api/types'
import { Avatar } from '../components/Avatar'
import { ConfirmDialog } from '../components/ConfirmDialog'
import { ArtistImage } from '../components/music/ArtistImage'
import { Cover } from '../components/music/Cover'
import { RequestStatusChip } from '../components/music/RequestStatusChip'
import { Segmented } from '../components/Segmented'
import { Button, ErrorBanner, PageLoading, PageTitle } from '../components/ui'
import { formatDateTime } from '../lib/format'
import { canRetry } from '../lib/requests'

const FILTERS = ['waiting', 'underway', 'done', 'problems', 'all'] as const
type Filter = (typeof FILTERS)[number]

function inFilter(request: MusicRequest, filter: Filter): boolean {
  switch (filter) {
    case 'waiting':
      return request.status === 'pending_approval'
    case 'underway':
      return request.status === 'approved' || request.status === 'searching'
    case 'done':
      return request.status === 'downloaded'
    case 'problems':
      return request.status === 'failed'
    default:
      return true
  }
}

/** Alle Anfragen fuer Admins: freigeben, ablehnen, erneut senden. */
export function AdminRequestsPage() {
  const { t, i18n } = useTranslation()
  const queryClient = useQueryClient()
  const [filter, setFilter] = useState<Filter>('waiting')
  const [rejecting, setRejecting] = useState<MusicRequest | null>(null)
  const [reason, setReason] = useState('')

  const query = useQuery({
    queryKey: ['admin-requests'],
    queryFn: () => api.get<MusicRequest[]>('/api/admin/requests'),
    refetchInterval: 30_000,
  })

  const refresh = () =>
    Promise.all([
      queryClient.invalidateQueries({ queryKey: ['admin-requests'] }),
      queryClient.invalidateQueries({ queryKey: ['admin-requests', 'pending_approval'] }),
    ])

  const act = useMutation({
    mutationFn: ({ id, action }: { id: number; action: 'approve' | 'retry' }) => api.post<MusicRequest>(`/api/admin/requests/${id}/${action}`),
    onSuccess: refresh,
  })
  const reject = useMutation({
    mutationFn: ({ id, text }: { id: number; text: string }) => api.post<MusicRequest>(`/api/admin/requests/${id}/reject`, { reason: text }),
    onSuccess: async () => {
      setRejecting(null)
      setReason('')
      await refresh()
    },
  })

  const all = useMemo(() => query.data ?? [], [query.data])
  const counts = useMemo(() => Object.fromEntries(FILTERS.map((item) => [item, all.filter((request) => inFilter(request, item)).length])), [all])
  const shown = all.filter((request) => inFilter(request, filter))

  return (
    <div className="flex flex-col gap-6">
      <PageTitle sub={t('adminRequests.intro')}>{t('adminRequests.title')}</PageTitle>
      <Segmented
        value={filter}
        options={FILTERS}
        onChange={setFilter}
        label={(option) => `${t(`adminRequests.filter_${option}`)} (${counts[option] ?? 0})`}
      />
      {act.isError && <ErrorBanner message={errorMessage(act.error)} />}
      {query.isPending && <PageLoading />}
      {query.isError && <ErrorBanner message={errorMessage(query.error)} />}
      {query.isSuccess && shown.length === 0 && (
        <p className="rounded-2xl border border-dashed border-ink-700 px-6 py-10 text-center text-sm text-mist-500">{t('adminRequests.empty')}</p>
      )}

      <ul className="flex flex-col gap-3">
        {shown.map((request) => {
          const name = request.user?.display_name || request.user?.username || '?'
          const retryable = canRetry(request)
          const wholeArtist = request.kind === 'artist'
          const target = wholeArtist ? `/kuenstler/${request.artist_mbid}` : `/album/${request.release_group_mbid}`
          return (
            <li key={request.id} className="flex flex-col gap-4 rounded-2xl border border-ink-700 bg-ink-850/80 p-4 sm:flex-row sm:items-center">
              <Link to={target} className="shrink-0">
                {wholeArtist ? (
                  <ArtistImage src={request.cover_url} name={request.artist_name} className="h-20 w-20 rounded-full border border-ink-700" />
                ) : (
                  <Cover src={request.cover_url} alt="" className="h-20 w-20 rounded-xl border border-ink-700" />
                )}
              </Link>
              <div className="flex min-w-0 flex-1 flex-col gap-1">
                <div className="flex flex-wrap items-center gap-2">
                  <Link to={target} className="font-semibold hover:text-accent-400">
                    {request.title}
                  </Link>
                  <RequestStatusChip request={request} />
                </div>
                <p className="text-sm text-mist-400">{wholeArtist ? t('artistRequest.kind') : request.artist_name}</p>
                <p className="flex items-center gap-2 text-xs text-mist-600">
                  <Avatar name={name} className="h-5 w-5 text-[9px]" />
                  {name} · {formatDateTime(request.requested_at, i18n.language)}
                </p>
                {request.error_code && request.error_code !== 'dry_run' && (
                  <p className="text-xs text-bad-500">
                    {storedError(request.error_code)}
                    {request.error_message ? ` (${request.error_message})` : ''}
                  </p>
                )}
                {request.rejection_reason && <p className="text-xs text-mist-500">„{request.rejection_reason}“</p>}
              </div>
              <div className="flex shrink-0 flex-wrap gap-2">
                {request.status === 'pending_approval' && (
                  <>
                    <Button variant="ghost" onClick={() => setRejecting(request)}>
                      {t('adminRequests.reject')}
                    </Button>
                    <Button loading={act.isPending && act.variables?.id === request.id} onClick={() => act.mutate({ id: request.id, action: 'approve' })}>
                      {t('adminRequests.approve')}
                    </Button>
                  </>
                )}
                {retryable && (
                  <Button
                    variant="ghost"
                    loading={act.isPending && act.variables?.id === request.id}
                    onClick={() => act.mutate({ id: request.id, action: 'retry' })}
                  >
                    {t('adminRequests.retry')}
                  </Button>
                )}
              </div>
            </li>
          )
        })}
      </ul>

      <ConfirmDialog
        open={rejecting !== null}
        title={t('adminRequests.rejectTitle')}
        description={t('adminRequests.rejectText', { title: rejecting?.title ?? '' })}
        confirmLabel={t('adminRequests.reject')}
        loading={reject.isPending}
        error={reject.isError ? errorMessage(reject.error) : null}
        onCancel={() => {
          setRejecting(null)
          setReason('')
        }}
        onConfirm={() => rejecting && reject.mutate({ id: rejecting.id, text: reason })}
      >
        <textarea
          value={reason}
          onChange={(event) => setReason(event.target.value)}
          maxLength={500}
          rows={3}
          placeholder={t('adminRequests.reasonPlaceholder')}
          className="mt-4 w-full rounded-xl border border-ink-700 bg-ink-900 px-4 py-2.5 text-sm text-mist-100 placeholder:text-mist-600 focus:border-accent-500 focus:outline-none"
        />
      </ConfirmDialog>
    </div>
  )
}
