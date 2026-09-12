import { useQuery } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { Link, useParams } from 'react-router-dom'

import { ApiError, api } from '../api/client'
import type { GenreAlbums, GenreArtists } from '../api/types'
import { AlbumCard } from '../components/music/AlbumCard'
import { ArtistCard } from '../components/music/ArtistCard'
import { Shelf, ShelfSkeleton } from '../components/music/Shelf'
import { SectionProblem } from '../components/SectionProblem'
import { PageTitle } from '../components/ui'
import { genreName, genrePath } from '../lib/genres'

/** Wie auf der Kuenstlerseite: Jeder Teil laedt fuer sich, das Backend hat bei MusicBrainz schon wiederholt. */
const SECTION = { retry: false, staleTime: 10 * 60_000 } as const

function SectionTitle({ children }: { children: string }) {
  return <h2 className="text-xl font-bold tracking-tight">{children}</h2>
}

/**
 * Ein Genre: beliebte Kuenstler, beliebte Alben und verwandte Genres zum Weiterklicken.
 * Die Alben stammen von den Kuenstlern des Genres und kommen deshalb erst nach ihnen.
 * Scheitern die Kuenstler, fehlt der Abschnitt der Alben, der Fehler steht schon darueber.
 */
export function GenrePage() {
  const { t } = useTranslation()
  const { tag = '' } = useParams()
  const artists = useQuery({
    queryKey: ['genre', tag, 'artists'],
    queryFn: () => api.get<GenreArtists>(`/api/genres/artists?tag=${encodeURIComponent(tag)}`),
    ...SECTION,
  })
  const albums = useQuery({
    queryKey: ['genre', tag, 'albums'],
    queryFn: () => api.get<GenreAlbums>(`/api/genres/albums?tag=${encodeURIComponent(tag)}`),
    enabled: artists.isSuccess,
    ...SECTION,
  })
  const related = artists.data?.related ?? []
  // Wie auf der Kuenstlerseite: Ohne Schluessel gibt ListenBrainz die Alben mancher Kuenstler nicht
  // heraus, am 12.09.2026 bei allen acht Spitzen des Schlagers. "Erneut versuchen" hilft da nicht.
  const albumsNeedToken = albums.error instanceof ApiError && albums.error.code === 'listenbrainz_token_required'

  return (
    <div className="flex flex-col gap-10">
      <div className="flex flex-col gap-4">
        <PageTitle sub={t('genre.intro')}>{genreName(tag, t)}</PageTitle>
        {related.length > 0 && (
          <nav aria-label={t('genre.related')} className="flex flex-wrap items-center gap-2">
            <span className="mr-1 text-sm text-mist-500">{t('genre.related')}</span>
            {related.map((other) => (
              <Link
                key={other}
                to={genrePath(other)}
                className="rounded-full border border-ink-700 bg-ink-850 px-3 py-1 text-sm text-mist-300 transition-colors hover:border-accent-600/60 hover:text-mist-100"
              >
                {genreName(other, t)}
              </Link>
            ))}
          </nav>
        )}
      </div>

      {artists.isPending ? (
        <ShelfSkeleton round />
      ) : artists.isError ? (
        <section className="flex flex-col gap-3">
          <SectionTitle>{t('genre.artists')}</SectionTitle>
          <SectionProblem error={artists.error} retrying={artists.isFetching} onRetry={() => void artists.refetch()} />
        </section>
      ) : artists.data.artists.length > 0 ? (
        <Shelf title={t('genre.artists')} hint={artists.data.ranked ? t('genre.ranked') : t('genre.unranked')}>
          {artists.data.artists.map((artist) => (
            <ArtistCard key={artist.mbid} artist={artist} />
          ))}
        </Shelf>
      ) : (
        <section className="flex flex-col gap-3">
          <SectionTitle>{t('genre.artists')}</SectionTitle>
          <p className="text-sm text-mist-500">{t('genre.noArtists')}</p>
        </section>
      )}

      {artists.isError || albumsNeedToken ? null : albums.isPending ? (
        <ShelfSkeleton />
      ) : albums.isError ? (
        <section className="flex flex-col gap-3">
          <SectionTitle>{t('genre.albums')}</SectionTitle>
          <SectionProblem error={albums.error} retrying={albums.isFetching} onRetry={() => void albums.refetch()} />
        </section>
      ) : albums.data.albums.length > 0 ? (
        <Shelf title={t('genre.albums')} hint={t('genre.albumsHint')}>
          {albums.data.albums.map((album) => (
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
      ) : (
        <section className="flex flex-col gap-3">
          <SectionTitle>{t('genre.albums')}</SectionTitle>
          <p className="text-sm text-mist-500">{albums.data.available ? t('genre.noAlbums') : t('genre.albumsOff')}</p>
        </section>
      )}
    </div>
  )
}
