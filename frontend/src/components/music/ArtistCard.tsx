import { useTranslation } from 'react-i18next'
import { Link } from 'react-router-dom'

import type { ArtistItem } from '../../api/types'
import { ArtistImage } from './ArtistImage'

/**
 * Ein Kuenstler als rundes Bild mit Namen. Traegt die Karte Gruende, steht
 * darunter, zu wem sie passt: Das ist der Kern von "wenn dir X gefaellt".
 */
export function ArtistCard({ artist, size = 'md' }: { artist: ArtistItem; size?: 'md' | 'lg' }) {
  const { t } = useTranslation()
  const width = size === 'lg' ? 'w-40 sm:w-44' : 'w-32 sm:w-36'
  const reasons = artist.reasons ?? []
  return (
    <Link
      to={`/kuenstler/${artist.mbid}`}
      state={{ artist: { name: artist.name, image: artist.image } }}
      className={`group flex ${width} shrink-0 snap-start flex-col items-center gap-3 text-center`}
    >
      <div className="relative aspect-square w-full">
        <div className="absolute inset-0 rounded-full bg-accent-500/0 blur-xl transition-colors duration-300 group-hover:bg-accent-500/25" />
        <ArtistImage
          src={artist.image}
          name={artist.name}
          className="relative aspect-square w-full rounded-full border border-ink-700 transition-transform duration-300 group-hover:scale-[1.04] group-hover:border-accent-500/60"
        />
        {artist.in_library && (
          <span className="absolute right-1 bottom-1 rounded-full bg-scrim px-2 py-0.5 text-[10px] font-semibold text-ok-500 ring-1 ring-ok-500/40">
            {t('status.inLibrary')}
          </span>
        )}
      </div>
      <div className="w-full min-w-0">
        <p className="truncate text-sm font-semibold text-mist-100 group-hover:text-accent-400">{artist.name}</p>
        {reasons.length > 0 && (
          <p className="mt-0.5 line-clamp-2 text-xs text-mist-500">{t('discover.likeReason', { names: reasons.join(t('common.and')) })}</p>
        )}
      </div>
    </Link>
  )
}
