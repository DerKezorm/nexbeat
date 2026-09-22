import de from '../i18n/whatsnew.de.json'
import en from '../i18n/whatsnew.en.json'

/**
 * "Was ist neu": ein redaktioneller Text je Fassung, kein Changelog. Wie in nexdeck und Nexview.
 *
 * ⚠️ Ein Eintrag braucht alle vier Felder (lead, sections, smallTitle, small), jeder Abschnitt title, body und
 * where. Fehlt etwas, faellt der Eintrag weg, ohne Meldung. In Nexview passierte das mehrfach; der Waechter in
 * `whatsnew.test.ts` haelt es fest.
 */
export interface WhatsNewSection {
  title: string
  body: string
  where: string
  /** Nur fuer Admins, etwa zu Einstellungen. */
  admin?: boolean
}

export interface WhatsNewEntry {
  lead: string
  sections: WhatsNewSection[]
  smallTitle: string
  small: string[]
}

type File = { entries: Record<string, unknown> }
export const FILES: Record<string, File> = { de, en }

export function isSection(value: unknown): value is WhatsNewSection {
  if (!value || typeof value !== 'object') return false
  const section = value as Record<string, unknown>
  return typeof section.title === 'string' && typeof section.body === 'string' && typeof section.where === 'string'
}

export function isEntry(value: unknown): value is WhatsNewEntry {
  if (!value || typeof value !== 'object') return false
  const entry = value as Record<string, unknown>
  return (
    typeof entry.lead === 'string' &&
    Array.isArray(entry.sections) &&
    entry.sections.every(isSection) &&
    typeof entry.smallTitle === 'string' &&
    Array.isArray(entry.small) &&
    entry.small.every((line) => typeof line === 'string')
  )
}

export function compareVersions(a: string, b: string): number {
  const left = a.split('.').map(Number)
  const right = b.split('.').map(Number)
  for (let index = 0; index < 3; index++) {
    if ((left[index] ?? 0) !== (right[index] ?? 0)) return (left[index] ?? 0) - (right[index] ?? 0)
  }
  return 0
}

/**
 * Die neueste Fassung mit einem Eintrag, hoechstens die laufende. 22.09.2026: Der Text fuer die naechste Fassung
 * stand schon im Code, die Fussleiste sagte 1.0.0, das Fenster 1.1.0.
 */
export function latestVersion(running?: string | null): string | null {
  const versions = Object.keys(FILES.en.entries).filter((version) => !running || compareVersions(version, running) <= 0)
  return versions.length ? versions.sort((a, b) => compareVersions(b, a))[0] : null
}

export function entryFor(version: string, language: string): WhatsNewEntry | null {
  const entry = (FILES[language] ?? FILES.en).entries[version]
  return isEntry(entry) ? entry : null
}

/** Soll das Fenster aufgehen? Nur fuer eine Fassung, die das Konto noch nicht gesehen hat, und nie rueckwaerts. */
export function unseen(seen: string | null | undefined, latest: string | null): boolean {
  if (!latest) return false
  return !seen || compareVersions(latest, seen) > 0
}
