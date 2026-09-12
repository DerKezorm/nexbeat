/**
 * Der Kaninchenbau: welche Kuenstler man zuletzt nacheinander geoeffnet hat.
 *
 * Liegt nur in dieser Sitzung des Browsers. Ein neuer Reiter faengt einen neuen
 * Weg an, und nichts davon verlaesst den Rechner.
 */

export type TrailStep = { mbid: string; name: string }

const KEY = 'nexbeat.trail'
const MAX_STEPS = 8

export function readTrail(): TrailStep[] {
  try {
    const parsed = JSON.parse(sessionStorage.getItem(KEY) ?? '[]')
    return Array.isArray(parsed) ? parsed.filter((step) => step && typeof step.mbid === 'string') : []
  } catch {
    return []
  }
}

/** Den Kuenstler anhaengen. Kommt er schon vor, wird der Weg dort abgeschnitten. */
export function stepInto(step: TrailStep): TrailStep[] {
  const trail = readTrail()
  const existing = trail.findIndex((item) => item.mbid === step.mbid)
  const next = existing >= 0 ? trail.slice(0, existing + 1) : [...trail, step].slice(-MAX_STEPS)
  try {
    sessionStorage.setItem(KEY, JSON.stringify(next))
  } catch {
    // Ohne Speicher gibt es eben keinen Weg.
  }
  return next
}
