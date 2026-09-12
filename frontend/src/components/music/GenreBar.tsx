import { useTranslation } from 'react-i18next'
import { Link } from 'react-router-dom'

import { MAIN_GENRES, genreName, genrePath } from '../../lib/genres'
import { Symbol } from '../Symbol'
import { Shelf } from './Shelf'

/** Wo das Leuchten in der Kachel sitzt. Es wechselt, damit die Leiste nicht wie ein Stempel aussieht. */
const GLOWS = ['-top-8 -right-6', '-bottom-10 -left-4', '-top-6 left-10', '-bottom-8 right-2'] as const

/** Die Hauptgenres als Kacheln unter dem Kopf der Entdecken-Seite. Jede fuehrt zur Seite des Genres. */
export function GenreBar() {
  const { t } = useTranslation()
  return (
    <Shelf title={t('discover.genres')} hint={t('discover.genresHint')}>
      {MAIN_GENRES.map((genre, index) => (
        <Link
          key={genre.tag}
          to={genrePath(genre.tag)}
          className="group relative flex h-24 w-40 shrink-0 snap-start items-end overflow-hidden rounded-2xl border border-ink-700 bg-ink-850 p-4 transition-all hover:-translate-y-1 hover:border-accent-600/60 hover:shadow-2xl hover:shadow-accent-700/20 sm:w-44"
        >
          <span
            aria-hidden="true"
            className={`absolute h-24 w-24 rounded-full bg-accent-500/25 blur-2xl transition-colors duration-300 group-hover:bg-accent-500/45 ${GLOWS[index % GLOWS.length]}`}
          />
          <Symbol name="note" className="absolute top-3 right-3 h-5 w-5 text-mist-600 transition-colors group-hover:text-accent-400" />
          <span className="relative text-base font-bold tracking-tight text-mist-100">{genreName(genre.tag, t)}</span>
        </Link>
      ))}
    </Shelf>
  )
}
