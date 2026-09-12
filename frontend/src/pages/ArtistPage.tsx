import { useEffect, useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { Link, useLocation, useParams } from 'react-router-dom'

import { ApiError, api, errorMessage } from '../api/client'
import type {
  ArtistDiscography,
  ArtistPageData,
  ArtistPopular,
  ArtistSimilar,
  ArtistTopTracks,
  DiscographyAlbum,
} from '../api/types'
import { AlbumCard } from '../components/music/AlbumCard'
import { ArtistCard } from '../components/music/ArtistCard'
import { ArtistImage } from '../components/music/ArtistImage'
import { ArtistRequestButton } from '../components/music/ArtistRequestButton'
import { Shelf, ShelfSkeleton } from '../components/music/Shelf'
import { TrackRow } from '../components/music/TrackRow'
import { usePlayer } from '../components/player/usePlayer'
import { Segmented } from '../components/Segmented'
import { Symbol } from '../components/Symbol'
import { Button, Card, ErrorBanner, PageLoading } from '../components/ui'
import { withDiscographyTypes } from '../lib/albums'
import { formatYear } from '../lib/format'
import { artistPreview, type ArtistPreview } from '../lib/preview'
import { stepInto, type TrailStep } from '../lib/trail'

const FILTERS = ['album', 'ep', 'single', 'other', 'all'] as const
type Filter = (typeof FILTERS)[number]
const PLAIN_TYPES = ['album', 'ep', 'single']
/**
 * Jeder Abschnitt laedt fuer sich und versucht es nicht selbst erneut: Das Backend
 * hat bei MusicBrainz schon wiederholt. Scheitert eine Quelle, sagt der Abschnitt
 * das und bietet einen neuen Versuch an.
 */
const SECTION = { retry: false, staleTime: 5 * 60_000 } as const

/**
 * Alben, EPs und Singles zaehlen nur ohne Zusatztyp. Live, Compilation, Remix und
 * alles Uebrige steht unter "Weitere". Bei einer Band mit vielen Mitschnitten
 * waren sonst 90 von 100 "Alben" Konzerte und Sammlungen.
 */
function matches(album: DiscographyAlbum, filter: Filter): boolean {
  if (filter === 'all') return true
  const primary = album.primary_type.toLowerCase()
  const plain = album.secondary_types.length === 0 && PLAIN_TYPES.includes(primary)
  if (filter === 'other') return !plain
  return plain && primary === filter
}

/** Eine Quelle hat gerade nicht geantwortet. Nie als "gibt es nicht" verkleiden. */
function SectionProblem({ error, retrying, onRetry }: { error: Error | null; retrying: boolean; onRetry: () => void }) {
  const { t } = useTranslation()
  return (
    <div className="flex flex-wrap items-center justify-between gap-3 rounded-2xl border border-dashed border-ink-700 px-5 py-4">
      <p className="text-sm text-mist-400">{errorMessage(error)}</p>
      <Button variant="ghost" onClick={onRetry} loading={retrying}>
        {t('common.tryAgain')}
      </Button>
    </div>
  )
}

function CoverSkeletons({ count, className }: { count: number; className: string }) {
  return (
    <div className={className}>
      {Array.from({ length: count }, (_, index) => (
        <div key={index} className="flex flex-col gap-2">
          <div className="aspect-square animate-pulse rounded-xl bg-ink-800" />
          <div className="h-3 w-3/4 animate-pulse rounded bg-ink-800" />
        </div>
      ))}
    </div>
  )
}

/** Solange der Kopf laedt: Bild und Name aus der Karte, der Rest als Platzhalter. */
function ArtistLoading({ preview }: { preview: ArtistPreview }) {
  const { t } = useTranslation()
  return (
    <div className="flex flex-col gap-12" role="status" aria-live="polite" aria-label={t('common.loading')}>
      <section className="relative -mx-4 -mt-8 overflow-hidden px-4 pt-10 pb-8 sm:-mx-6 sm:px-6">
        <div className="nv-backdrop pointer-events-none absolute inset-0" aria-hidden="true">
          <ArtistImage src={preview.image} name={preview.name} className="h-full w-full scale-125 opacity-35 blur-3xl" />
          <div className="absolute inset-0 bg-linear-to-b from-ink-950/30 via-ink-950/70 to-ink-950" />
        </div>
        <div className="relative flex flex-col items-center gap-6 text-center sm:flex-row sm:items-end sm:text-left">
          <ArtistImage
            src={preview.image}
            name={preview.name}
            className="h-44 w-44 shrink-0 rounded-full border-2 border-ink-700 shadow-2xl shadow-accent-700/30 sm:h-56 sm:w-56"
          />
          <div className="flex min-w-0 flex-col items-center gap-3 sm:items-start">
            <div className="h-4 w-36 animate-pulse rounded bg-ink-800" />
            <h1 className="text-4xl font-bold tracking-tight break-words sm:text-6xl">
              {preview.name}
              <span className="text-accent-500">.</span>
            </h1>
            <div className="flex gap-1.5">
              <div className="h-5 w-16 animate-pulse rounded-full bg-ink-800" />
              <div className="h-5 w-20 animate-pulse rounded-full bg-ink-800" />
              <div className="h-5 w-14 animate-pulse rounded-full bg-ink-800" />
            </div>
          </div>
        </div>
      </section>
      <ShelfSkeleton />
    </div>
  )
}

export function ArtistPage() {
  const { t } = useTranslation()
  const { mbid = '' } = useParams()
  const location = useLocation()
  const player = usePlayer()
  const [chosen, setChosen] = useState<{ mbid: string; filter: Filter } | null>(null)
  const [trail, setTrail] = useState<TrailStep[]>([])

  const query = useQuery({
    queryKey: ['artist', mbid],
    queryFn: () => api.get<ArtistPageData>(`/api/artists/${mbid}`),
    staleTime: 5 * 60_000,
  })
  const data = query.data
  const discography = useQuery({
    queryKey: ['artist', mbid, 'discography'],
    queryFn: () => api.get<ArtistDiscography>(`/api/artists/${mbid}/discography`),
    ...SECTION,
  })
  const popularQuery = useQuery({
    queryKey: ['artist', mbid, 'popular'],
    queryFn: () => api.get<ArtistPopular>(`/api/artists/${mbid}/popular`),
    ...SECTION,
  })
  const similarQuery = useQuery({
    queryKey: ['artist', mbid, 'similar'],
    queryFn: () => api.get<ArtistSimilar>(`/api/artists/${mbid}/similar`),
    ...SECTION,
  })
  const name = data?.artist.name ?? ''
  const topTracks = useQuery({
    queryKey: ['artist', mbid, 'top-tracks', name],
    queryFn: () => api.get<ArtistTopTracks>(`/api/artists/${mbid}/top-tracks?name=${encodeURIComponent(name)}`),
    enabled: Boolean(data?.sources.deezer && name),
    ...SECTION,
  })

  useEffect(() => {
    if (data) setTrail(stepInto({ mbid: data.artist.mbid, name: data.artist.name }))
  }, [data])

  const allAlbums = useMemo(() => discography.data?.albums ?? [], [discography.data])
  const counts = useMemo(() => {
    const result: Record<Filter, number> = { album: 0, ep: 0, single: 0, other: 0, all: 0 }
    for (const album of allAlbums) {
      for (const option of FILTERS) {
        if (matches(album, option)) result[option] += 1
      }
    }
    return result
  }, [allAlbums])
  // Bis jemand selbst waehlt, die erste Reihe mit Inhalt. Die Wahl gilt nur fuer diesen Kuenstler.
  const filter: Filter =
    chosen?.mbid === mbid ? chosen.filter : (FILTERS.find((option) => option !== 'all' && counts[option] > 0) ?? 'all')
  const visibleFilters = FILTERS.filter((option) => option === 'all' || counts[option] > 0)
  const albums = useMemo(() => allAlbums.filter((album) => matches(album, filter)), [allAlbums, filter])

  if (query.isPending) {
    const preview = artistPreview(location.state)
    return preview ? <ArtistLoading preview={preview} /> : <PageLoading />
  }
  if (query.isError || !data) return <ErrorBanner message={errorMessage(query.error)} />

  const { artist } = data
  const popular = withDiscographyTypes(popularQuery.data?.albums ?? [], allAlbums)
  const similar = similarQuery.data?.artists ?? []
  const tracks = topTracks.data?.tracks ?? []
  const previews = tracks.filter((track) => track.preview)
  // Ohne Schluessel gibt ListenBrainz die Beliebtheit nicht heraus. Ein Hinweis auf jeder Seite hilft niemandem.
  const popularBlocked = popularQuery.error instanceof ApiError && popularQuery.error.code === 'listenbrainz_token_required'
  const showPopular = data.sources.listenbrainz && !popularBlocked && (popularQuery.isPending || popularQuery.isError || popular.length > 0)
  const showTracks = data.sources.deezer && (topTracks.isPending || topTracks.isError || previews.length > 0)
  const years = [formatYear(artist.begin), formatYear(artist.end)].filter(Boolean).join(' – ')
  const meta = [artist.type ? t(`artistType.${artist.type.toLowerCase()}`, { defaultValue: artist.type }) : '', artist.country, years]
    .filter(Boolean)
    .join(' · ')

  return (
    <div className="flex flex-col gap-12">
      <section className="relative -mx-4 -mt-8 overflow-hidden px-4 pt-10 pb-8 sm:-mx-6 sm:px-6">
        <div className="nv-backdrop pointer-events-none absolute inset-0" aria-hidden="true">
          <ArtistImage src={artist.image} name={artist.name} className="h-full w-full scale-125 opacity-35 blur-3xl" />
          <div className="absolute inset-0 bg-linear-to-b from-ink-950/30 via-ink-950/70 to-ink-950" />
        </div>
        <div className="relative flex flex-col items-center gap-6 text-center sm:flex-row sm:items-end sm:text-left animate-nv-fade">
          <ArtistImage
            src={artist.image}
            name={artist.name}
            className="h-44 w-44 shrink-0 rounded-full border-2 border-ink-700 shadow-2xl shadow-accent-700/30 sm:h-56 sm:w-56"
          />
          <div className="flex min-w-0 flex-col gap-3">
            <div className="flex flex-wrap items-center justify-center gap-2 sm:justify-start">
              {artist.in_library && (
                <span className="rounded-full bg-ok-500/15 px-2.5 py-0.5 text-xs font-semibold text-ok-500 ring-1 ring-ok-500/40">
                  {t('artist.inLibrary')}
                </span>
              )}
              {meta && <span className="text-sm text-mist-400">{meta}</span>}
            </div>
            <h1 className="text-4xl font-bold tracking-tight break-words sm:text-6xl">
              {artist.name}
              <span className="text-accent-500">.</span>
            </h1>
            {artist.disambiguation && <p className="text-sm text-mist-500">{artist.disambiguation}</p>}
            {artist.tags.length > 0 && (
              <div className="flex flex-wrap justify-center gap-1.5 sm:justify-start">
                {artist.tags.map((tag) => (
                  <span key={tag} className="rounded-full border border-ink-700 bg-ink-900/70 px-2.5 py-0.5 text-xs text-mist-300">
                    {tag}
                  </span>
                ))}
              </div>
            )}
            <div className="mt-1 flex flex-wrap justify-center gap-2 sm:justify-start">
              {previews.length > 0 && (
                <button
                  type="button"
                  onClick={() =>
                    player.play({
                      key: `top:${artist.mbid}:0`,
                      url: previews[0].preview,
                      title: previews[0].title,
                      artist: artist.name,
                      cover: previews[0].cover,
                    })
                  }
                  className="inline-flex items-center gap-2 rounded-full bg-accent-500 px-5 py-2.5 text-sm font-semibold text-white shadow-lg shadow-accent-700/25 transition-colors hover:bg-accent-400"
                >
                  <Symbol name="play" className="h-4 w-4" />
                  {t('artist.listen')}
                </button>
              )}
              <ArtistRequestButton data={data} />
              <a
                href={`https://musicbrainz.org/artist/${artist.mbid}`}
                target="_blank"
                rel="noreferrer"
                className="inline-flex items-center gap-2 rounded-full border border-ink-700 bg-ink-850 px-5 py-2.5 text-sm font-semibold text-mist-300 transition-colors hover:text-mist-100"
              >
                <Symbol name="link" className="h-4 w-4" />
                MusicBrainz
              </a>
            </div>
          </div>
        </div>
      </section>

      {(showPopular || showTracks) && (
        <div className="grid gap-8 lg:grid-cols-[1.4fr_1fr]">
          {showPopular && (
            <section className="flex flex-col gap-3">
              <h2 className="text-xl font-bold tracking-tight">{t('artist.popular')}</h2>
              {popularQuery.isPending ? (
                <CoverSkeletons count={4} className="grid grid-cols-2 gap-4 sm:grid-cols-4" />
              ) : popularQuery.isError ? (
                <SectionProblem error={popularQuery.error} retrying={popularQuery.isFetching} onRetry={() => void popularQuery.refetch()} />
              ) : (
                <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
                  {popular.slice(0, 4).map((album) => (
                    <AlbumCard
                      key={album.mbid}
                      mbid={album.mbid}
                      title={album.title}
                      cover={album.cover}
                      date={album.date}
                      type={album.primary_type}
                      secondaryTypes={album.secondary_types}
                      library={album.library}
                      request={album.request}
                    />
                  ))}
                </div>
              )}
            </section>
          )}
          {showTracks && (
            <Card className="flex flex-col gap-2 p-4">
              <h2 className="px-3 pt-1 text-lg font-bold tracking-tight">{t('artist.topTracks')}</h2>
              {topTracks.isPending ? (
                <div className="flex flex-col gap-2 px-3 pb-2">
                  {Array.from({ length: 6 }, (_, index) => (
                    <div key={index} className="h-9 animate-pulse rounded-lg bg-ink-800/60" />
                  ))}
                </div>
              ) : topTracks.isError ? (
                <SectionProblem error={topTracks.error} retrying={topTracks.isFetching} onRetry={() => void topTracks.refetch()} />
              ) : (
                <ol className="flex flex-col">
                  {tracks.slice(0, 8).map((track, index) => (
                    <TrackRow
                      key={`${track.title}-${index}`}
                      number={index + 1}
                      title={track.title}
                      sub={track.album_title}
                      seconds={track.duration}
                      explicit={track.explicit}
                      track={
                        track.preview
                          ? { key: `top:${artist.mbid}:${index}`, url: track.preview, title: track.title, artist: artist.name, cover: track.cover }
                          : null
                      }
                    />
                  ))}
                </ol>
              )}
            </Card>
          )}
        </div>
      )}

      <section className="flex flex-col gap-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <h2 className="text-xl font-bold tracking-tight">{t('artist.discography')}</h2>
          {discography.isSuccess && allAlbums.length > 0 && (
            <Segmented
              value={filter}
              options={visibleFilters}
              onChange={(next) => setChosen({ mbid, filter: next })}
              label={(option) => `${t(`artist.filter_${option}`)} (${counts[option]})`}
            />
          )}
        </div>
        {discography.isPending ? (
          <CoverSkeletons count={12} className="grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-5 xl:grid-cols-6" />
        ) : discography.isError ? (
          <SectionProblem error={discography.error} retrying={discography.isFetching} onRetry={() => void discography.refetch()} />
        ) : albums.length === 0 ? (
          <p className="text-sm text-mist-500">{t('artist.noReleases')}</p>
        ) : (
          <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-5 xl:grid-cols-6">
            {albums.map((album) => (
              <AlbumCard
                key={album.mbid}
                mbid={album.mbid}
                title={album.title}
                cover={album.cover}
                date={album.date}
                type={album.primary_type}
                secondaryTypes={album.secondary_types}
                library={album.library}
                request={album.request}
              />
            ))}
          </div>
        )}
      </section>

      {!data.sources.listenbrainz ? (
        <p className="text-sm text-mist-500">{t('artist.similarOff')}</p>
      ) : similarQuery.isPending ? (
        <ShelfSkeleton round />
      ) : similarQuery.isError ? (
        <section className="flex flex-col gap-3">
          <h2 className="text-xl font-bold tracking-tight">{t('artist.similar')}</h2>
          <SectionProblem error={similarQuery.error} retrying={similarQuery.isFetching} onRetry={() => void similarQuery.refetch()} />
        </section>
      ) : similar.length > 0 ? (
        <Shelf
          title={t('artist.similar')}
          hint={
            trail.length > 1 ? (
              <span className="flex flex-wrap items-center gap-1">
                {t('artist.trail')}
                {trail.map((step, index) => (
                  <span key={step.mbid} className="flex items-center gap-1">
                    {index > 0 && <span aria-hidden="true">›</span>}
                    {step.mbid === artist.mbid ? (
                      <span className="font-semibold text-mist-300">{step.name}</span>
                    ) : (
                      <Link to={`/kuenstler/${step.mbid}`} className="text-accent-500 hover:text-accent-400">
                        {step.name}
                      </Link>
                    )}
                  </span>
                ))}
              </span>
            ) : (
              t('artist.similarHint')
            )
          }
        >
          {similar.map((item) => (
            <ArtistCard key={item.mbid} artist={item} />
          ))}
        </Shelf>
      ) : null}
    </div>
  )
}
