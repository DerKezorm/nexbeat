import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type { ReactNode } from 'react'
import { useTranslation } from 'react-i18next'

import { Cover } from '../music/Cover'
import { Symbol } from '../Symbol'
import { PlayerContext, type PlayerTrack } from './PlayerContext'

/**
 * Ein Player fuer die ganze Seite. Es laeuft immer nur eine Hoerprobe: Wer
 * eine neue startet, beendet die alte. Die Leiste unten bleibt beim
 * Seitenwechsel stehen, damit man beim Stoebern weiterhoeren kann.
 */
export function PlayerProvider({ children }: { children: ReactNode }) {
  const audioRef = useRef<HTMLAudioElement | null>(null)
  const [current, setCurrent] = useState<PlayerTrack | null>(null)
  const [playing, setPlaying] = useState(false)
  const [progress, setProgress] = useState(0)

  const audio = useCallback((): HTMLAudioElement => {
    if (!audioRef.current) {
      const element = new Audio()
      element.preload = 'none'
      element.addEventListener('timeupdate', () =>
        setProgress(element.duration ? element.currentTime / element.duration : 0),
      )
      element.addEventListener('play', () => setPlaying(true))
      element.addEventListener('pause', () => setPlaying(false))
      element.addEventListener('ended', () => {
        setPlaying(false)
        setProgress(1)
      })
      audioRef.current = element
    }
    return audioRef.current
  }, [])

  useEffect(() => () => audioRef.current?.pause(), [])

  const play = useCallback(
    (track: PlayerTrack) => {
      const element = audio()
      if (current?.key === track.key) {
        if (element.paused) void element.play().catch(() => setPlaying(false))
        else element.pause()
        return
      }
      element.src = track.url
      setCurrent(track)
      setProgress(0)
      void element.play().catch(() => setPlaying(false))
    },
    [audio, current],
  )

  const stop = useCallback(() => {
    const element = audioRef.current
    if (element) {
      element.pause()
      element.removeAttribute('src')
    }
    setCurrent(null)
    setPlaying(false)
    setProgress(0)
  }, [])

  const value = useMemo(() => ({ current, playing, progress, play, stop }), [current, playing, progress, play, stop])

  return (
    <PlayerContext.Provider value={value}>
      {children}
      {current && <PlayerBar track={current} playing={playing} progress={progress} onToggle={() => play(current)} onStop={stop} />}
    </PlayerContext.Provider>
  )
}

function PlayerBar({
  track,
  playing,
  progress,
  onToggle,
  onStop,
}: {
  track: PlayerTrack
  playing: boolean
  progress: number
  onToggle: () => void
  onStop: () => void
}) {
  const { t } = useTranslation()
  return (
    <div className="fixed bottom-4 left-1/2 z-40 w-[min(34rem,calc(100%-2rem))] -translate-x-1/2 overflow-hidden rounded-2xl border border-ink-700 bg-ink-850/95 shadow-2xl shadow-black/60 backdrop-blur-xl animate-nv-rise">
      <div className="flex items-center gap-3 p-3">
        <Cover src={track.cover} alt="" className="h-12 w-12 rounded-lg" />
        <div className="min-w-0 flex-1">
          <p className="truncate text-sm font-semibold">{track.title}</p>
          <p className="flex items-center gap-2 truncate text-xs text-mist-500">
            {playing && <Equalizer />}
            {track.artist} · {t('player.preview')}
          </p>
        </div>
        <button
          type="button"
          onClick={onToggle}
          aria-label={playing ? t('player.pause') : t('player.play')}
          className="flex h-10 w-10 items-center justify-center rounded-full bg-accent-500 text-white shadow-lg shadow-accent-700/30 transition-colors hover:bg-accent-400"
        >
          <Symbol name={playing ? 'pause' : 'play'} className="h-4 w-4" />
        </button>
        <button
          type="button"
          onClick={onStop}
          aria-label={t('player.close')}
          className="flex h-9 w-9 items-center justify-center rounded-full text-mist-500 transition-colors hover:bg-ink-800 hover:text-mist-100"
        >
          <Symbol name="close" />
        </button>
      </div>
      <div className="h-1 bg-ink-800">
        <div className="h-full bg-accent-500 transition-[width] duration-200" style={{ width: `${Math.round(progress * 100)}%` }} />
      </div>
    </div>
  )
}

/** Drei Balken, die sich bewegen, solange etwas laeuft. */
export function Equalizer() {
  return (
    <span className="inline-flex h-3 items-end gap-0.5" aria-hidden="true">
      {[0, 0.2, 0.4].map((delay) => (
        <span key={delay} className="block h-3 w-0.5 rounded-full bg-accent-400 animate-nb-eq" style={{ animationDelay: `${delay}s` }} />
      ))}
    </span>
  )
}
