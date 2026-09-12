import { useContext } from 'react'

import { AuthContext, type AuthState } from './AuthContext'

export function useAuth(): AuthState {
  const value = useContext(AuthContext)
  if (!value) throw new Error('useAuth needs an AuthProvider')
  return value
}
