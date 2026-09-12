import { useState } from 'react'
import type { FormEvent } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { Link, useNavigate } from 'react-router-dom'

import { api, errorMessage } from '../api/client'
import type { AlbumItem, ArtistItem, DiscoverResponse, DiscoverRow } from '../api/types'
import { useAuth } from '../auth/useAuth'
import { AlbumCard } from '../components/music/AlbumCard'
import { ArtistCard } from '../components/music/ArtistCard'
import { ArtistImage } from '../components/music/ArtistImage'
import { Shelf, ShelfSkeleton } from '../components/music/Shelf'
import { Symbol } from '../components/Symbol'
import { ErrorBanner } from '../components/ui'

function rowTitle(row: DiscoverRow, t: (key: string, options?: Record<string, unknown>) => string) {
  if (row.id === 'for_you') return { title: t('discover.forYou'), hint: t('discover.forYouHint') }
  if (row.id.startsWith('because:')) {
    return { title: t('discover.becauseYouListen', { name: row.params?.name ?? '' }), hint: t('discover.becauseHint') }
  }
  if (row.id === 'trending_albums') return { title: t('discover.trendingAlbums'), hint: t('discover.trendingHint') }
  return { title: t('discover.trendingArtists'), hint: t('discover.trendingHint') }
}

/** Oben die Frage "was hoere ich als Naechstes?", mit einem Kuenstler, der sie beantwortet. */
function Hero({ spotlight }: { spotlight: ArtistItem | null }) {
  const { t } = useTranslation()
  const { user } = useAuth()
  const navigate = useNavigate()
  const [query, setQuery] = useState('')

  function search(event: FormEvent) {
    event.preventDefault()
    if (query.trim().length >= 2) navigate(`/suche?q=${encodeURIComponent(query.trim())}`)
  }

  return (
    <section className="relative overflow-hidden rounded-3xl border border-ink-700 bg-ink-900/60 animate-nv-fade">
      {spotlight && (
        <div className="nv-backdrop pointer-events-none absolute inset-0" aria-hidden="true">
          <ArtistImage src={spotlight.image} name={spotlight.name} className="h-full w-full scale-110 opacity-40 blur-3xl" />
          <div className="absolute inset-0 bg-linear-to-r from-ink-950 via-ink-950/85 to-ink-950/40" />
        </div>
      )}
      <div className="relative grid gap-8 p-6 sm:p-10 lg:grid-cols-[1.3fr_1fr] lg:items-center">
        <div className="flex flex-col gap-5">
          <p className="text-sm font-medium text-accent-400">{t('discover.greeting', { name: user?.display_name || user?.username })}</p>
          <h1 className="text-4xl leading-tight font-bold tracking-tight sm:text-5xl">
            {t('discover.heroTitle')}
            <span className="text-accent-500">.</span>
          </h1>
          <p className="max-w-xl text-base text-mist-400">{t('discover.heroIntro')}</p>
          <form onSubmit={search} className="flex max-w-xl items-center gap-2 rounded-full border border-ink-700 bg-ink-950/70 p-1.5 pl-5 focus-within:border-accent-500">
            <Symbol name="search" className="h-5 w-5 text-mist-500" />
            <input
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder={t('search.placeholder')}
              aria-label={t('search.placeholder')}
              className="min-w-0 flex-1 bg-transparent py-2 text-sm text-mist-100 placeholder:text-mist-600 focus:outline-none"
            />
            <button type="submit" className="rounded-full bg-accent-500 px-5 py-2 text-sm font-semibold text-white transition-colors hover:bg-accent-400">
              {t('search.submit')}
            </button>
          </form>
        </div>

        {spotlight && (
          <Link
            to={`/kuenstler/${spotlight.mbid}`}
            className="group relative flex items-center gap-5 rounded-2xl border border-ink-700/80 bg-ink-850/70 p-5 backdrop-blur transition-colors hover:border-accent-500/60"
          >
            <ArtistImage
              src={spotlight.image}
              name={spotlight.name}
              className="h-28 w-28 shrink-0 rounded-full border border-ink-700 shadow-2xl shadow-accent-700/30 transition-transform duration-300 group-hover:scale-105 sm:h-32 sm:w-32"
            />
            <div className="min-w-0">
              <p className="flex items-center gap-1.5 text-xs font-semibold tracking-wide text-accent-400 uppercase">
                <Symbol name="sparkle" className="h-3.5 w-3.5" />
                {t('discover.spotlight')}
              </p>
              <p className="mt-1 truncate text-2xl font-bold">{spotlight.name}</p>
              {spotlight.reasons && spotlight.reasons.length > 0 && (
                <p className="mt-1 line-clamp-2 text-sm text-mist-400">
                  {t('discover.likeReason', { names: spotlight.reasons.join(t('common.and')) })}
                </p>
              )}
              <p className="mt-3 inline-flex items-center gap-1.5 text-sm font-semibold text-mist-200 group-hover:text-accent-400">
                {t('discover.openArtist')}
                <Symbol name="arrow" className="h-4 w-4" />
              </p>
            </div>
          </Link>
        )}
      </div>
    </section>
  )
}

export function HomePage() {
  const { t } = useTranslation()
  const { user } = useAuth()
  const query = useQuery({
    queryKey: ['discover'],
    queryFn: () => api.get<DiscoverResponse>('/api/discover'),
    staleTime: 5 * 60_000,
  })

  const rows = query.data?.rows ?? []
  const forYou = rows.find((row) => row.id === 'for_you')
  const spotlight = (forYou?.items[0] as ArtistItem | undefined) ?? null

  return (
    <div className="flex flex-col gap-12">
      <Hero spotlight={spotlight} />

      {query.isPending && (
        <div className="flex flex-col gap-10">
          <ShelfSkeleton round />
          <ShelfSkeleton />
        </div>
      )}
      {query.isError && <ErrorBanner message={errorMessage(query.error)} />}

      {rows.map((row, index) => {
        const { title, hint } = rowTitle(row, t)
        const action =
          row.id.startsWith('because:') && row.params?.mbid ? (
            <Link to={`/kuenstler/${row.params.mbid}`} className="shrink-0 text-sm font-semibold text-accent-500 hover:text-accent-400">
              {t('discover.openSeed', { name: row.params.name })}
            </Link>
          ) : undefined
        return (
          <Shelf key={row.id} title={title} hint={hint} action={action} delay={index * 80}>
            {row.kind === 'artists'
              ? (row.items as ArtistItem[]).map((artist) => <ArtistCard key={artist.mbid} artist={artist} />)
              : (row.items as AlbumItem[]).map((album) => (
                  <AlbumCard
                    key={album.mbid}
                    mbid={album.mbid}
                    title={album.title}
                    subtitle={album.artist_name}
                    cover={album.cover}
                    request={album.request}
                    inRow
                  />
                ))}
          </Shelf>
        )
      })}

      {query.isSuccess && rows.length === 0 && (
        <div className="flex flex-col items-center gap-3 rounded-2xl border border-dashed border-ink-700 px-6 py-14 text-center">
          <Symbol name="sparkle" className="h-8 w-8 text-accent-500" />
          <h2 className="text-lg font-semibold">{t('discover.emptyTitle')}</h2>
          <p className="max-w-md text-sm text-mist-500">
            {user?.is_admin && !query.data.requests_enabled ? t('discover.emptyAdmin') : t('discover.emptyUser')}
          </p>
          <div className="mt-2 flex flex-wrap justify-center gap-2">
            <Link to="/suche" className="rounded-full bg-accent-500 px-5 py-2.5 text-sm font-semibold text-white hover:bg-accent-400">
              {t('discover.emptySearch')}
            </Link>
            {user?.is_admin && (
              <Link
                to="/admin/einstellungen?reiter=lidarr"
                className="rounded-full border border-ink-700 bg-ink-850 px-5 py-2.5 text-sm font-semibold text-mist-300 hover:text-mist-100"
              >
                {t('discover.emptySettings')}
              </Link>
            )}
          </div>
        </div>
      )}
    </div>
  )
}
