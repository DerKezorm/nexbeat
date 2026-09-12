import { useEffect, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { useSearchParams } from 'react-router-dom'

import { api, errorMessage } from '../api/client'
import type { SearchAlbum, SearchArtist } from '../api/types'
import { AlbumCard } from '../components/music/AlbumCard'
import { ArtistCard } from '../components/music/ArtistCard'
import { Shelf, ShelfSkeleton } from '../components/music/Shelf'
import { Symbol } from '../components/Symbol'
import { ErrorBanner, PageTitle } from '../components/ui'

/**
 * Suche in MusicBrainz. Kuenstler und Alben sind zwei getrennte Abfragen: Die
 * Kuenstler stehen da, waehrend die Alben noch kommen. MusicBrainz nimmt nur
 * eine Anfrage pro Sekunde an, der Server reiht sie ein.
 */
export function SearchPage() {
  const { t } = useTranslation()
  const [params, setParams] = useSearchParams()
  const term = params.get('q') ?? ''
  const [input, setInput] = useState(term)

  useEffect(() => setInput(term), [term])

  // Erst nach einer kurzen Pause tippen suchen, sonst geht jeder Buchstabe raus.
  useEffect(() => {
    const trimmed = input.trim()
    if (trimmed === term) return
    const timer = window.setTimeout(() => setParams(trimmed ? { q: trimmed } : {}, { replace: true }), 450)
    return () => window.clearTimeout(timer)
  }, [input, term, setParams])

  const enabled = term.length >= 2
  const artists = useQuery({
    queryKey: ['search', 'artists', term],
    queryFn: () => api.get<SearchArtist[]>(`/api/search/artists?q=${encodeURIComponent(term)}`),
    enabled,
    staleTime: 10 * 60_000,
  })
  const albums = useQuery({
    queryKey: ['search', 'albums', term],
    queryFn: () => api.get<SearchAlbum[]>(`/api/search/albums?q=${encodeURIComponent(term)}`),
    enabled,
    staleTime: 10 * 60_000,
  })

  return (
    <div className="flex flex-col gap-8">
      <PageTitle sub={t('search.intro')}>{t('search.title')}</PageTitle>

      <label className="flex items-center gap-3 rounded-2xl border border-ink-700 bg-ink-900 px-5 py-4 focus-within:border-accent-500">
        <Symbol name="search" className="h-5 w-5 text-mist-500" />
        <input
          value={input}
          onChange={(event) => setInput(event.target.value)}
          placeholder={t('search.placeholder')}
          aria-label={t('search.placeholder')}
          autoFocus
          className="min-w-0 flex-1 bg-transparent text-lg text-mist-100 placeholder:text-mist-600 focus:outline-none"
        />
      </label>

      {!enabled && (
        <div className="flex flex-col items-center gap-3 rounded-2xl border border-dashed border-ink-700 px-6 py-14 text-center">
          <Symbol name="note" className="h-8 w-8 text-accent-500" />
          <p className="max-w-md text-sm text-mist-500">{t('search.idle')}</p>
        </div>
      )}

      {enabled && (
        <>
          {artists.isPending ? (
            <ShelfSkeleton round />
          ) : artists.isError ? (
            <ErrorBanner message={errorMessage(artists.error)} />
          ) : artists.data.length > 0 ? (
            <Shelf title={t('search.artists')}>
              {artists.data.map((artist) => (
                <ArtistCard key={artist.mbid} artist={artist} />
              ))}
            </Shelf>
          ) : null}

          <section className="flex flex-col gap-3">
            <h2 className="text-xl font-bold tracking-tight">{t('search.albums')}</h2>
            {albums.isPending ? (
              <p className="text-sm text-mist-500">{t('search.albumsLoading')}</p>
            ) : albums.isError ? (
              <ErrorBanner message={errorMessage(albums.error)} />
            ) : albums.data.length === 0 ? (
              <p className="text-sm text-mist-500">{t('search.nothing')}</p>
            ) : (
              <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-5 xl:grid-cols-6">
                {albums.data.map((album) => (
                  <AlbumCard
                    key={album.mbid}
                    mbid={album.mbid}
                    title={album.title}
                    subtitle={album.artist_name}
                    cover={album.cover}
                    date={album.first_release_date}
                    type={album.primary_type}
                    request={album.request}
                  />
                ))}
              </div>
            )}
          </section>
        </>
      )}
    </div>
  )
}
