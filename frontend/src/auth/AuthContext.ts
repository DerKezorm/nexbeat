import { createContext } from 'react'

import type { AppConfig, Me } from '../api/types'
import type { TokenPair } from '../api/client'

export type AuthState = {
  status: 'loading' | 'ready'
  user: Me | null
  config: AppConfig | null
  needsSetup: boolean
  login: (login: string, password: string) => Promise<void>
  startSession: (tokens: TokenPair) => Promise<void>
  logout: () => Promise<void>
  refreshUser: () => Promise<void>
  updateUser: (user: Me) => void
}

export const AuthContext = createContext<AuthState | null>(null)
