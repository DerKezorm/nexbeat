/**
 * Zugriff auf das nexbeat-Backend, gebaut wie in Nexview.
 *
 * Der Zugangs-Token liegt nur im Arbeitsspeicher. Das Erneuerungs-Token ist ein
 * HttpOnly-Cookie, das dieses Skript weder lesen noch schreiben kann. Nach einem
 * Neuladen holt `restoreSession` mit dem Cookie einen neuen Zugangs-Token.
 */

import i18n from '../i18n'

let accessToken: string | null = null
let onSessionLost: (() => void) | null = null

export type TokenPair = {
  access_token: string
  token_type: string
  expires_in: number
}

export class ApiError extends Error {
  status: number
  code: string | null
  data: Record<string, unknown> | null

  constructor(status: number, message: string, code: string | null = null, data: Record<string, unknown> | null = null) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.code = code
    this.data = data
  }
}

export function setTokens(tokens: TokenPair): void {
  accessToken = tokens.access_token
}

export function clearTokens(): void {
  accessToken = null
}

export async function logout(): Promise<void> {
  accessToken = null
  try {
    await fetch('/api/auth/logout', { method: 'POST', credentials: 'same-origin' })
  } catch {
    // Server nicht erreichbar. Der Arbeitsspeicher ist trotzdem leer.
  }
}

export function setSessionLostHandler(handler: (() => void) | null): void {
  onSessionLost = handler
}

/**
 * Fehlermeldungen des Servers in der eingestellten Sprache.
 *
 * ⚠️ Das Backend benennt nur (`code`), der Satz entsteht hier aus
 * `errors.byCode` in `de.json` und `en.json`. `message` ist der englische
 * Rueckfall fuer eine Kennung ohne Uebersetzung.
 */
export function translateError(detail: Record<string, unknown>, status: number): string {
  const code = typeof detail.code === 'string' ? detail.code : null
  const fallback = String(detail.message ?? `HTTP ${status}`)
  if (!code) return fallback
  const special = SPECIAL_CASES[code]
  if (special) return special(detail)
  const key = `errors.byCode.${code}`
  return i18n.exists(key) ? i18n.t(key, { ...detail }) : fallback
}

/** Die wenigen Meldungen, deren Satz nicht durch blosses Einsetzen entsteht. */
const SPECIAL_CASES: Record<string, (detail: Record<string, unknown>) => string> = {
  internal_error: (detail) => i18n.t('errors.internal', { id: String(detail.request_id ?? '?') }),
  too_many_attempts: (detail) => {
    const seconds = Math.max(1, Math.ceil(Number(detail.retry_after ?? 1)))
    return seconds >= 60
      ? i18n.t('errors.tooManyAttemptsMinutes', { count: Math.ceil(seconds / 60) })
      : i18n.t('errors.tooManyAttemptsSeconds', { count: seconds })
  },
}

async function parseError(response: Response): Promise<{ message: string; code: string | null; data: Record<string, unknown> | null }> {
  try {
    const body = await response.json()
    const detail = body?.detail
    if (typeof detail === 'string') return { message: detail, code: null, data: null }
    if (detail && typeof detail === 'object' && !Array.isArray(detail)) {
      return {
        message: translateError(detail as Record<string, unknown>, response.status),
        code: typeof detail.code === 'string' ? detail.code : null,
        data: detail as Record<string, unknown>,
      }
    }
  } catch {
    /* Antwort war kein JSON */
  }
  return { message: i18n.t('errors.http', { status: response.status }), code: null, data: null }
}

/** Laufende Erneuerung, damit parallel abgelaufene Anfragen nur eine ausloesen. */
let runningRefresh: Promise<boolean> | null = null

async function refreshAccessToken(): Promise<boolean> {
  if (runningRefresh) return runningRefresh
  runningRefresh = (async () => {
    try {
      const response = await fetch('/api/auth/refresh', { method: 'POST', credentials: 'same-origin' })
      if (!response.ok) {
        clearTokens()
        return false
      }
      setTokens((await response.json()) as TokenPair)
      return true
    } catch {
      return false
    } finally {
      runningRefresh = null
    }
  })()
  return runningRefresh
}

type RequestOptions = { method?: string; body?: unknown; auth?: boolean }

async function send<T>(path: string, options: RequestOptions, retry: boolean): Promise<T> {
  const { method = 'GET', body, auth = true } = options
  const headers: Record<string, string> = {}
  if (body !== undefined) headers['Content-Type'] = 'application/json'
  if (auth && accessToken) headers.Authorization = `Bearer ${accessToken}`

  let response: Response
  try {
    response = await fetch(path, { method, headers, body: body === undefined ? undefined : JSON.stringify(body) })
  } catch {
    throw new ApiError(0, i18n.t('errors.network'), 'network')
  }

  if (response.status === 401 && auth && retry) {
    if (await refreshAccessToken()) return send<T>(path, options, false)
    clearTokens()
    onSessionLost?.()
  }

  if (!response.ok) {
    const info = await parseError(response)
    throw new ApiError(response.status, info.message, info.code, info.data)
  }
  if (response.status === 204) return undefined as T
  return (await response.json()) as T
}

export const api = {
  get: <T>(path: string, options: Omit<RequestOptions, 'method' | 'body'> = {}) =>
    send<T>(path, { ...options, method: 'GET' }, true),
  post: <T>(path: string, body?: unknown, options: Omit<RequestOptions, 'method'> = {}) =>
    send<T>(path, { ...options, method: 'POST', body }, true),
  put: <T>(path: string, body?: unknown, options: Omit<RequestOptions, 'method'> = {}) =>
    send<T>(path, { ...options, method: 'PUT', body }, true),
  patch: <T>(path: string, body?: unknown, options: Omit<RequestOptions, 'method'> = {}) =>
    send<T>(path, { ...options, method: 'PATCH', body }, true),
  delete: <T>(path: string, options: Omit<RequestOptions, 'method'> = {}) =>
    send<T>(path, { ...options, method: 'DELETE' }, true),
}

export async function restoreSession(): Promise<boolean> {
  if (accessToken) return true
  return refreshAccessToken()
}

/** Die gespeicherte Kennung einer Anfrage als Satz, sonst nichts. */
export function storedError(code: string | null | undefined): string | null {
  if (!code) return null
  const key = `errors.byCode.${code}`
  return i18n.exists(key) ? i18n.t(key) : code
}

export function errorMessage(error: unknown): string {
  return error instanceof ApiError ? error.message : i18n.t('errors.generic')
}
