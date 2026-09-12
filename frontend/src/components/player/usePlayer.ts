import { useContext } from 'react'

import { PlayerContext, type PlayerState } from './PlayerContext'

export function usePlayer(): PlayerState {
  const value = useContext(PlayerContext)
  if (!value) throw new Error('usePlayer needs a PlayerProvider')
  return value
}
