/**
 * Datum und Dauer in der eingestellten Sprache.
 *
 * ⚠️ Der Server rechnet in UTC. Manche Zeitpunkte kommen mit ``Z``, manche ohne
 * Zeitzone (SQLite kennt keine). Ohne Zone wird hier UTC angenommen, sonst
 * verschiebt der Browser sie um die eigene Zeitzone.
 */

export function parseServerDate(value: string | null | undefined): Date | null {
  if (!value) return null
  const hasZone = /(z|[+-]\d\d:?\d\d)$/i.test(value)
  const date = new Date(hasZone ? value : `${value}Z`)
  return Number.isNaN(date.getTime()) ? null : date
}

export function formatDate(value: string | null | undefined, language: string): string {
  const date = parseServerDate(value)
  if (!date) return ''
  return new Intl.DateTimeFormat(language, { dateStyle: 'medium' }).format(date)
}

export function formatDateTime(value: string | null | undefined, language: string): string {
  const date = parseServerDate(value)
  if (!date) return ''
  return new Intl.DateTimeFormat(language, { dateStyle: 'medium', timeStyle: 'short' }).format(date)
}

/** "2024-05-01" oder "2024" wird "2024". */
export function formatYear(value: string | null | undefined): string {
  return value ? value.slice(0, 4) : ''
}

/** Sekunden als m:ss. */
export function formatDuration(seconds: number | null | undefined): string {
  if (!seconds || seconds < 0) return ''
  const minutes = Math.floor(seconds / 60)
  const rest = Math.round(seconds % 60)
  return `${minutes}:${String(rest).padStart(2, '0')}`
}
