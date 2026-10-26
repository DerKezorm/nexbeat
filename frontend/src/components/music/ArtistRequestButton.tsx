import { useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'

import { api, errorMessage, storedError } from '../../api/client'
import type { ArtistPageData, CreatedRequest } from '../../api/types'
import { useAuth } from '../../auth/useAuth'
import { albumTypeList, bringsMany } from '../../lib/albumTypes'
import { formatDate } from '../../lib/format'
import { ConfirmDialog } from '../ConfirmDialog'
import { Symbol } from '../Symbol'
import { AlbumTypePicker } from './AlbumTypePicker'
import { RequestStatusChip } from './RequestStatusChip'
import { useTarget } from '../../lib/target'

/**
 * Der ganze Kuenstler auf einmal: alle Studioalben und die kuenftigen. Zaehlt als
 * eine Anfrage. Die Rueckfrage sagt vorher, was genau passiert und was nicht.
 * Mit nexcrate als Ziel waehlt man dort die Arten, vorgewaehlt ist der Standard des Admins.
 */
export function ArtistRequestButton({ data }: { data: ArtistPageData }) {
  const { t, i18n } = useTranslation()
  const target = useTarget()
  const { user, refreshUser } = useAuth()
  const queryClient = useQueryClient()
  const [asking, setAsking] = useState(false)
  const { artist, request, quota } = data
  const choosing = data.album_types !== null
  const [types, setTypes] = useState<string[]>(data.album_types ?? [])

  const create = useMutation({
    mutationFn: () =>
      api.post<CreatedRequest>('/api/requests/artist', choosing ? { artist_mbid: artist.mbid, types } : { artist_mbid: artist.mbid }),
    onSuccess: async (created) => {
      // Eine sofort gescheiterte Anfrage zaehlt nicht, und danach stuende wieder der Knopf
      // da. Die Rueckfrage bleibt dann offen und sagt, warum.
      if (created.request.status !== 'failed') setAsking(false)
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['artist', artist.mbid] }),
        queryClient.invalidateQueries({ queryKey: ['my-requests'] }),
        refreshUser(),
      ])
    },
  })

  if (request) {
    return (
      <span className="inline-flex items-center gap-2 rounded-full border border-ink-700 bg-ink-850 px-4 py-2 text-sm font-semibold text-mist-300">
        {t('artistRequest.kind')}
        {choosing && request.album_types && <span className="font-normal text-mist-500">{albumTypeList(t, request.album_types)}</span>}
        <RequestStatusChip request={request} />
      </span>
    )
  }
  if (!data.requests_enabled) return null
  if (data.blocked) {
    // 12.09.2026: Mit einem weiten Metadatenprofil brachte "Ganzer Kuenstler" weit ueber tausend Alben nach Lidarr.
    return (
      <span
        role="note"
        className="inline-flex max-w-md items-start gap-2 rounded-2xl border border-ink-700 bg-ink-850 px-4 py-2 text-left text-xs text-mist-400"
      >
        <Symbol name="inbox" className="mt-0.5 h-4 w-4 shrink-0 text-mist-500" />
        <span className="flex flex-col gap-0.5">
          <span className="font-semibold text-mist-300">
            {t('artistRequest.kind')} · {t('request.blocked')}
          </span>
          <span>{storedError(data.blocked)}</span>
        </span>
      </span>
    )
  }

  const exhausted = quota.limit !== null && quota.used >= quota.limit
  let problem: string | null = null
  if (create.isError) {
    problem = errorMessage(create.error)
  } else if (create.data?.request.status === 'failed') {
    problem = t('request.failedNow', { reason: storedError(create.data.request.error_code) ?? '' }).trim()
  }
  return (
    <>
      <button
        type="button"
        disabled={exhausted}
        title={exhausted ? t('quota.exhaustedUntil', { date: formatDate(quota.resets_at, i18n.language) }) : undefined}
        onClick={() => {
          create.reset()
          setTypes(data.album_types ?? [])
          setAsking(true)
        }}
        className="inline-flex items-center gap-2 rounded-full border border-accent-600/60 bg-accent-700/15 px-5 py-2.5 text-sm font-semibold text-accent-400 transition-colors hover:bg-accent-700/25 disabled:cursor-not-allowed disabled:opacity-50"
      >
        <Symbol name="inbox" className="h-4 w-4" />
        {t('artistRequest.button')}
      </button>
      <ConfirmDialog
        open={asking}
        title={t('artistRequest.title', { name: artist.name })}
        description={
          <div className="flex flex-col gap-2">
            {choosing ? (
              <>
                <p>{t('artistRequest.textChoice', { target })}</p>
                <AlbumTypePicker label={t('artistRequest.typesLabel')} value={types} onChange={setTypes} />
                {bringsMany(types) && <p className="text-warn-500">{t('artistRequest.many')}</p>}
                <p className="text-mist-500">{t('artistRequest.editions')}</p>
              </>
            ) : (
              <p>{t('artistRequest.text', { target })}</p>
            )}
            <p className="text-mist-500">{t('artistRequest.counts')}</p>
            {data.requires_approval && <p className="text-warn-500">{t('request.needsApproval')}</p>}
            {data.dry_run && user?.is_admin && <p className="text-warn-500">{t('request.dryRunHint', { target })}</p>}
          </div>
        }
        confirmLabel={t('artistRequest.confirm')}
        loading={create.isPending}
        error={problem}
        onCancel={() => setAsking(false)}
        onConfirm={() => create.mutate()}
      />
    </>
  )
}
