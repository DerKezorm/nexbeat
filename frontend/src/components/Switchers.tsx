import { useState } from 'react'
import { useTranslation } from 'react-i18next'

import { api } from '../api/client'
import type { Me } from '../api/types'
import { useAuth } from '../auth/useAuth'
import { changeLanguage, SUPPORTED_LANGUAGES, type Language } from '../i18n'
import { applyTheme, storedTheme, type Theme } from '../lib/theme'

/** Deutsch/Englisch. Angemeldet wird die Wahl im Konto gespeichert. */
export function LanguageSwitcher() {
  const { t, i18n } = useTranslation()
  const { user, updateUser } = useAuth()

  async function select(language: Language) {
    if (language === i18n.language) return
    await changeLanguage(language)
    if (user) {
      try {
        updateUser(await api.patch<Me>('/api/auth/me', { language }))
      } catch {
        // Umgestellt ist trotzdem, nur das Speichern schlug fehl.
      }
    }
  }

  return (
    <div className="flex items-center rounded-full border border-ink-700 bg-ink-850 p-0.5" role="group" aria-label={t('language.label')}>
      {SUPPORTED_LANGUAGES.map((language) => {
        const active = i18n.language === language
        return (
          <button
            key={language}
            type="button"
            onClick={() => void select(language)}
            aria-pressed={active}
            className={
              'rounded-full px-2.5 py-1 text-xs font-semibold uppercase transition-colors ' +
              (active ? 'bg-accent-500 text-white' : 'text-mist-500 hover:text-mist-100')
            }
          >
            {language}
          </button>
        )
      })}
    </div>
  )
}

function MoonIcon() {
  return (
    <svg viewBox="0 0 20 20" className="h-3.5 w-3.5" fill="currentColor" aria-hidden="true">
      <path d="M17.3 12.9A7.5 7.5 0 0 1 7.1 2.7a.8.8 0 0 0-1-1 9.1 9.1 0 1 0 12.2 12.2.8.8 0 0 0-1-1Z" />
    </svg>
  )
}

function SunIcon() {
  return (
    <svg viewBox="0 0 20 20" className="h-3.5 w-3.5" fill="currentColor" aria-hidden="true">
      <path d="M10 14a4 4 0 1 1 0-8 4 4 0 0 1 0 8Zm0-10.8a.9.9 0 0 1-.9-.9V1.9a.9.9 0 0 1 1.8 0v.4a.9.9 0 0 1-.9.9Zm0 15.6a.9.9 0 0 1-.9-.9v-.4a.9.9 0 0 1 1.8 0v.4a.9.9 0 0 1-.9.9ZM18.1 10.9h-.4a.9.9 0 0 1 0-1.8h.4a.9.9 0 0 1 0 1.8Zm-15.8 0h-.4a.9.9 0 0 1 0-1.8h.4a.9.9 0 0 1 0 1.8Z" />
    </svg>
  )
}

/** Hell/Dunkel. Die Wahl bleibt im Browser. */
export function ThemeSwitcher() {
  const { t } = useTranslation()
  const [theme, setTheme] = useState<Theme>(storedTheme())

  function select(next: Theme) {
    applyTheme(next)
    setTheme(next)
  }

  const modes: { value: Theme; label: string; icon: () => React.ReactElement }[] = [
    { value: 'dark', label: t('theme.dark'), icon: MoonIcon },
    { value: 'light', label: t('theme.light'), icon: SunIcon },
  ]

  return (
    <div className="flex items-center rounded-full border border-ink-700 bg-ink-850 p-0.5" role="group" aria-label={t('theme.label')}>
      {modes.map(({ value, label, icon: Icon }) => (
        <button
          key={value}
          type="button"
          onClick={() => select(value)}
          aria-pressed={theme === value}
          title={label}
          aria-label={label}
          className={
            'rounded-full p-1.5 transition-colors ' +
            (theme === value ? 'bg-accent-500 text-white' : 'text-mist-500 hover:text-mist-100')
          }
        >
          <Icon />
        </button>
      ))}
    </div>
  )
}
