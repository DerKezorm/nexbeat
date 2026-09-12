import { useTranslation } from 'react-i18next'
import { Link } from 'react-router-dom'

import type { LibraryState, RequestState } from '../../api/types'
import { formatYear } from '../../lib/format'
import { Cover } from './Cover'
import { StatusBadge } from './StatusBadge'

type AlbumCardProps = {
  mbid: string
  title: string
  cover: string
  subtitle?: string
  date?: string
  type?: string
  /** Zusatztypen wie Live oder Compilation, in den Namen von MusicBrainz. */
  secondaryTypes?: string[]
  library?: LibraryState | null
  request?: RequestState | null
  /** In Reihen feste Breite, im Raster volle Breite. */
  inRow?: boolean
}

/** Das Album als quadratisches Cover, mit Zustand oben links. Hover wie die Kacheln in Nexview. */
export function AlbumCard({ mbid, title, cover, subtitle, date, type, secondaryTypes = [], library, request, inRow = false }: AlbumCardProps) {
  const { t } = useTranslation()
  const typeLabel = type ? t(`releaseType.${type.toLowerCase()}`, { defaultValue: type }) : ''
  const meta = [formatYear(date), typeLabel, ...secondaryTypes].filter(Boolean).join(' · ')
  return (
    <Link
      to={`/album/${mbid}`}
      state={{ album: { title, cover, artist: subtitle ?? '' } }}
      className={
        'group flex flex-col overflow-hidden rounded-xl border border-ink-700 bg-ink-850 transition-all ' +
        'hover:-translate-y-1 hover:border-accent-600/60 hover:shadow-2xl hover:shadow-accent-700/20 ' +
        (inRow ? 'w-40 shrink-0 snap-start sm:w-44' : '')
      }
    >
      <div className="relative aspect-square overflow-hidden bg-ink-900">
        <Cover src={cover} alt="" className="h-full w-full transition-transform duration-300 group-hover:scale-105" />
        <div className="absolute top-2 left-2">
          <StatusBadge library={library} request={request} overImage />
        </div>
      </div>
      <div className="flex flex-1 flex-col gap-0.5 p-3">
        <h3 className="line-clamp-2 text-sm leading-snug font-semibold">{title}</h3>
        {subtitle && <p className="truncate text-xs text-mist-400">{subtitle}</p>}
        {meta && <p className="mt-auto pt-1 text-xs text-mist-600">{meta}</p>}
      </div>
    </Link>
  )
}
