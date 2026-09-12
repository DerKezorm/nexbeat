import { createContext } from 'react'

export type PlayerTrack = {
  /** Eindeutig je Titel, damit ein zweiter Klick pausiert statt neu startet. */
  key: string
  url: string
  title: string
  artist: string
  cover?: string
}

export type PlayerState = {
  current: PlayerTrack | null
  playing: boolean
  progress: number
  play: (track: PlayerTrack) => void
  stop: () => void
}

export const PlayerContext = createContext<PlayerState | null>(null)
