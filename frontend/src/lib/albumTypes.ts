import type { TFunction } from 'i18next'

/** nexcrates Gruppen, in der Reihenfolge ihrer Kuenstlerseite. Gleich `services/album_groups.py`. */
export const ALBUM_TYPES = ['studio', 'ep', 'single', 'live', 'compilation', 'soundtrack', 'remix', 'spoken', 'other'] as const

export type AlbumType = (typeof ALBUM_TYPES)[number]

/** Arten, die bei bekannten Kuenstlern schnell Hunderte Eintraege bringen. Dann sagt der Dialog es vorher. */
const MANY = new Set<string>(['single', 'live', 'compilation', 'remix', 'other'])

export function bringsMany(types: readonly string[]): boolean {
  return types.some((type) => MANY.has(type))
}

/** "Studioalben, Live-Alben" fuer Listen und Abzeichen. */
export function albumTypeList(t: TFunction, types: readonly string[] = []): string {
  return ALBUM_TYPES.filter((type) => types.includes(type))
    .map((type) => t(`albumTypes.${type}`))
    .join(', ')
}

/** "Ganzer Kuenstler · Studioalben, Live-Alben" in den Anfragelisten. */
export function artistKindLabel(t: TFunction, types?: readonly string[]): string {
  const list = albumTypeList(t, types)
  return list ? `${t('artistRequest.kind')} · ${list}` : t('artistRequest.kind')
}
