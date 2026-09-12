import { useCallback, useEffect, useMemo, useState } from 'react'
import type { ReactNode } from 'react'
import { useQueryClient } from '@tanstack/react-query'

import { api, logout as serverLogout, restoreSession, setSessionLostHandler, setTokens } from '../api/client'
import type { TokenPair } from '../api/client'
import type { AppConfig, Me } from '../api/types'
import { changeLanguage, isLanguage } from '../i18n'
import { AuthContext } from './AuthContext'

/**
 * Wer angemeldet ist, und ob es die Installation schon gibt.
 *
 * Beim Start zuerst die oeffentliche Konfiguration (braucht es die
 * Erst-Einrichtung?), dann der Versuch, die Sitzung aus dem Cookie zu holen.
 * Sein 401 ist keine Stoerung, sondern die Antwort "niemand angemeldet".
 */
export function AuthProvider({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient()
  const [status, setStatus] = useState<'loading' | 'ready'>('loading')
  const [user, setUser] = useState<Me | null>(null)
  const [config, setConfig] = useState<AppConfig | null>(null)

  const loadUser = useCallback(async () => {
    const me = await api.get<Me>('/api/auth/me')
    setUser(me)
    if (isLanguage(me.language)) await changeLanguage(me.language)
  }, [])

  useEffect(() => {
    let cancelled = false
    setSessionLostHandler(() => {
      setUser(null)
      queryClient.clear()
    })
    ;(async () => {
      try {
        const loaded = await api.get<AppConfig>('/api/config', { auth: false })
        if (cancelled) return
        setConfig(loaded)
        if (!loaded.needs_setup && (await restoreSession())) await loadUser()
      } catch {
        // Backend nicht erreichbar: Die Anmeldeseite zeigt den Fehler beim Versuch.
      } finally {
        if (!cancelled) setStatus('ready')
      }
    })()
    return () => {
      cancelled = true
      setSessionLostHandler(null)
    }
  }, [loadUser, queryClient])

  const startSession = useCallback(
    async (tokens: TokenPair) => {
      setTokens(tokens)
      setConfig((current) => (current ? { ...current, needs_setup: false } : current))
      await loadUser()
    },
    [loadUser],
  )

  const login = useCallback(
    async (loginName: string, password: string) => {
      const tokens = await api.post<TokenPair>('/api/auth/login', { login: loginName, password }, { auth: false })
      await startSession(tokens)
    },
    [startSession],
  )

  const logout = useCallback(async () => {
    await serverLogout()
    queryClient.clear()
    setUser(null)
  }, [queryClient])

  const value = useMemo(
    () => ({
      status,
      user,
      config,
      needsSetup: config?.needs_setup ?? false,
      login,
      startSession,
      logout,
      refreshUser: loadUser,
      updateUser: setUser,
    }),
    [status, user, config, login, startSession, logout, loadUser],
  )

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}
