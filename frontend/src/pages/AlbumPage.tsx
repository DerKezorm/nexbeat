import { useQuery } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { Link, useLocation, useParams } from 'react-router-dom'

import { api, errorMessage } from '../api/client'
import type { AlbumPageData } from '../api/types'
import { ArtistImage } from '../components/music/ArtistImage'
import { Cover } from '../components/music/Cover'
import { RequestPanel } from '../components/music/RequestPanel'
import { StatusBadge } from '../components/music/StatusBadge'
import { TrackRow } from '../components/music/TrackRow'
import { Card, ErrorBanner, PageLoading } from '../components/ui'
import { formatYear } from '../lib/format'
import { albumPreview, type AlbumPreview } from '../lib/preview'

/**
 * Solange MusicBrainz antwortet: Cover und Titel aus der Karte, der Rest als
 * Platzhalter. Zur Spitzenzeit stand hier sonst sekundenlang nur ein Kreisel.
 */
function AlbumLoading({ preview }: { preview: AlbumPreview }) {
  const { t } = useTranslation()
  return (
    <div className="flex flex-col gap-10" role="status" aria-live="polite" aria-label={t('common.loading')}>
      <section className="relative -mx-4 -mt-8 overflow-hidden px-4 pt-10 pb-6 sm:-mx-6 sm:px-6">
        <div className="nv-backdrop pointer-events-none absolute inset-0" aria-hidden="true">
          <Cover src={preview.cover} alt="" className="h-full w-full scale-125 opacity-40 blur-3xl" />
          <div className="absolute inset-0 bg-linear-to-b from-ink-950/30 via-ink-950/75 to-ink-950" />
        </div>
        <div className="relative grid gap-8 lg:grid-cols-[auto_1fr_20rem] lg:items-end">
          <Cover
            src={preview.cover}
            alt={preview.title}
            className="mx-auto aspect-square w-60 rounded-2xl border border-ink-700 shadow-2xl shadow-black/60 sm:w-72 lg:mx-0"
          />
          <div className="flex min-w-0 flex-col items-center gap-3 text-center lg:items-start lg:text-left">
            <div className="h-4 w-44 animate-pulse rounded bg-ink-800" />
            <h1 className="text-3xl font-bold tracking-tight break-words sm:text-5xl">
              {preview.title}
              <span className="text-accent-500">.</span>
            </h1>
            {preview.artist ? (
              <p className="text-lg font-semibold text-mist-200">{preview.artist}</p>
            ) : (
              <div className="h-6 w-40 animate-pulse rounded bg-ink-800" />
            )}
          </div>
          <div className="h-44 animate-pulse rounded-2xl border border-ink-700 bg-ink-850/60" />
        </div>
      </section>
      <Card className="flex flex-col gap-3 p-4">
        <div className="mx-3 mt-1 h-5 w-20 animate-pulse rounded bg-ink-800" />
        {Array.from({ length: 6 }, (_, index) => (
          <div key={index} className="mx-3 h-10 animate-pulse rounded-lg bg-ink-800/60" />
        ))}
      </Card>
    </div>
  )
}

export function AlbumPage() {
  const { t } = useTranslation()
  const { mbid = '' } = useParams()
  const location = useLocation()
  const query = useQuery({
    queryKey: ['album', mbid],
    queryFn: () => api.get<AlbumPageData>(`/api/albums/${mbid}`),
    staleTime: 60_000,
  })

  if (query.isPending) {
    const preview = albumPreview(location.state)
    return preview ? <AlbumLoading preview={preview} /> : <PageLoading />
  }
  if (query.isError || !query.data) return <ErrorBanner message={errorMessage(query.error)} />
  const data = query.data
  const { album } = data
  const discs = new Set(data.tracks.map((track) => track.disc)).size
  const meta = [
    album.primary_type ? t(`releaseType.${album.primary_type.toLowerCase()}`, { defaultValue: album.primary_type }) : '',
    ...album.secondary_types,
    formatYear(album.date),
    data.tracks.length ? t('album.trackCount', { count: data.tracks.length }) : '',
  ]
    .filter(Boolean)
    .join(' · ')

  return (
    <div className="flex flex-col gap-10">
      <section className="relative -mx-4 -mt-8 overflow-hidden px-4 pt-10 pb-6 sm:-mx-6 sm:px-6">
        <div className="nv-backdrop pointer-events-none absolute inset-0" aria-hidden="true">
          <Cover src={album.cover} alt="" className="h-full w-full scale-125 opacity-40 blur-3xl" />
          <div className="absolute inset-0 bg-linear-to-b from-ink-950/30 via-ink-950/75 to-ink-950" />
        </div>
        <div className="relative grid gap-8 lg:grid-cols-[auto_1fr_20rem] lg:items-end">
          <Cover
            src={album.cover}
            alt={album.title}
            className="mx-auto aspect-square w-60 rounded-2xl border border-ink-700 shadow-2xl shadow-black/60 sm:w-72 lg:mx-0 animate-nv-fade"
          />
          <div className="flex min-w-0 flex-col items-center gap-3 text-center lg:items-start lg:text-left">
            <div className="flex flex-wrap items-center justify-center gap-2 lg:justify-start">
              <StatusBadge library={data.library} request={data.request} />
              {meta && <span className="text-sm text-mist-400">{meta}</span>}
            </div>
            <h1 className="text-3xl font-bold tracking-tight break-words sm:text-5xl">
              {album.title}
              <span className="text-accent-500">.</span>
            </h1>
            <Link
              to={`/kuenstler/${album.artist_mbid}`}
              state={{ artist: { name: album.artist_name, image: album.artist_image } }}
              className="group flex items-center gap-3"
            >
              <ArtistImage src={album.artist_image} name={album.artist_name} className="h-9 w-9 rounded-full border border-ink-700" />
              <span className="text-lg font-semibold text-mist-200 group-hover:text-accent-400">{album.artist_name}</span>
            </Link>
          </div>
          <RequestPanel data={data} />
        </div>
      </section>

      <Card className="flex flex-col gap-2 p-4">
        <h2 className="px-3 pt-1 text-lg font-bold tracking-tight">{t('album.tracks')}</h2>
        {data.tracks.length === 0 ? (
          <p className="px-3 pb-2 text-sm text-mist-500">{t('album.noTracks')}</p>
        ) : (
          <ol className="flex flex-col">
            {data.tracks.map((track, index) => (
              <TrackRow
                key={`${track.disc}-${track.position}-${index}`}
                number={discs > 1 ? `${track.disc}.${track.position}` : track.position}
                title={track.title}
                seconds={track.length_ms ? track.length_ms / 1000 : null}
                explicit={track.explicit}
                track={
                  track.preview
                    ? {
                        key: `album:${album.mbid}:${index}`,
                        url: track.preview,
                        title: track.title,
                        artist: album.artist_name,
                        cover: album.cover,
                      }
                    : null
                }
              />
            ))}
          </ol>
        )}
        {data.tracks.some((track) => track.preview) && <p className="px-3 pt-2 text-xs text-mist-600">{t('album.previewSource')}</p>}
      </Card>
    </div>
  )
}
