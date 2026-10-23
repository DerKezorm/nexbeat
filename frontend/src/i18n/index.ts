/**
 * Die Sprachen, und nur die, die gerade gebraucht wird. Die andere kommt erst
 * beim Umschalten nach. Deshalb gibt es keine Rueckfallsprache: Fehlt ein Text,
 * erscheint sein Schluessel. `vollstaendig.test.ts` sorgt dafuer, dass beide
 * Dateien dieselben Eintraege haben.
 */

import i18n from 'i18next'
import { initReactI18next } from 'react-i18next'

import { oidcVariables, oidcWording, type OidcWording } from '../vendor/nexoidc/oidc'

export const SUPPORTED_LANGUAGES = ['de', 'en'] as const
export type Language = (typeof SUPPORTED_LANGUAGES)[number]

const STORAGE_KEY = 'nexbeat.language'

type Texts = Record<string, unknown>

/**
 * Die Texte einer Sprache: die eigenen von nexbeat und die des gemeinsamen Anmeldemoduls (Namensraum `oidc`,
 * wortgleich in allen Apps). `{{app}}` und `{{slug}}` darin setzt `defaultVariables` unten.
 */
const TEXTS: Record<Language, () => Promise<Texts>> = {
  de: async () => merged((await import('./de.json')).default, (await import('../vendor/nexoidc/oidc.de.json')).default),
  en: async () => merged((await import('./en.json')).default, (await import('../vendor/nexoidc/oidc.en.json')).default),
}

function merged(own: Texts, module: OidcWording): Texts {
  return { ...own, ...oidcWording(module, { singleAccount: false, invitations: true }) }
}

export function isLanguage(value: unknown): value is Language {
  return value === 'de' || value === 'en'
}

function initialLanguage(): Language {
  try {
    const stored = localStorage.getItem(STORAGE_KEY)
    if (isLanguage(stored)) return stored
  } catch {
    // Privater Modus ohne localStorage.
  }
  return navigator.language.toLowerCase().startsWith('de') ? 'de' : 'en'
}

async function load(language: Language): Promise<void> {
  if (i18n.hasResourceBundle(language, 'translation')) return
  i18n.addResourceBundle(language, 'translation', await TEXTS[language]())
}

export async function startI18n(language: Language = initialLanguage()): Promise<void> {
  const texts = await TEXTS[language]()
  await i18n.use(initReactI18next).init({
    resources: { [language]: { translation: texts } },
    lng: language,
    fallbackLng: false,
    interpolation: { escapeValue: false, defaultVariables: oidcVariables('nexbeat') },
  })
  document.documentElement.lang = language
}

export async function changeLanguage(language: Language): Promise<void> {
  try {
    localStorage.setItem(STORAGE_KEY, language)
  } catch {
    // Dann gilt die Wahl nur bis zum Neuladen.
  }
  if (i18n.language === language) return
  await load(language)
  document.documentElement.lang = language
  await i18n.changeLanguage(language)
}

export default i18n
