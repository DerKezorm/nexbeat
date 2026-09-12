import { useTranslation } from 'react-i18next'

import { formatDuration } from '../../lib/format'
import { Equalizer } from '../player/PlayerProvider'
import { usePlayer } from '../player/usePlayer'
import type { PlayerTrack } from '../player/PlayerContext'
import { Symbol } from '../Symbol'

/** Eine Zeile einer Titelliste. Mit Hoerprobe wird die Nummer zum Abspielknopf. */
export function TrackRow({
  number,
  title,
  seconds,
  explicit,
  track,
  sub,
}: {
  number: number | string
  title: string
  seconds: number | null
  explicit: boolean
  track: PlayerTrack | null
  sub?: string
}) {
  const { t } = useTranslation()
  const player = usePlayer()
  const active = track !== null && player.current?.key === track.key
  const playing = active && player.playing

  return (
    <li
      className={
        'group flex items-center gap-3 rounded-xl px-3 py-2 transition-colors ' +
        (active ? 'bg-accent-500/10' : 'hover:bg-ink-800/70')
      }
    >
      <div className="flex w-8 shrink-0 justify-center">
        {track ? (
          <button
            type="button"
            onClick={() => player.play(track)}
            aria-label={playing ? t('player.pause') : t('player.playTitle', { title })}
            className={
              'flex h-8 w-8 items-center justify-center rounded-full transition-colors ' +
              (active ? 'bg-accent-500 text-white' : 'text-mist-500 group-hover:bg-accent-500 group-hover:text-white')
            }
          >
            {playing ? <Equalizer /> : <Symbol name="play" className="h-3.5 w-3.5" />}
          </button>
        ) : (
          <span className="text-sm text-mist-600 tabular-nums">{number}</span>
        )}
      </div>
      <div className="min-w-0 flex-1">
        <p className={'truncate text-sm ' + (active ? 'font-semibold text-accent-400' : 'text-mist-200')}>{title}</p>
        {sub && <p className="truncate text-xs text-mist-600">{sub}</p>}
      </div>
      {explicit && (
        <span className="rounded bg-ink-700 px-1.5 py-0.5 text-[10px] font-bold text-mist-300" title={t('album.explicit')}>
          E
        </span>
      )}
      <span className="w-12 shrink-0 text-right text-xs text-mist-600 tabular-nums">{formatDuration(seconds)}</span>
    </li>
  )
}
