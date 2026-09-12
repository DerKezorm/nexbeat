/**
 * Heller oder dunkler Modus. Die Farben dahinter stehen allein in
 * styles/index.css, hier steht nur, welcher Modus gilt.
 */

export type Theme = 'dark' | 'light'

const KEY = 'nexbeat.theme'

export function storedTheme(): Theme {
  try {
    return localStorage.getItem(KEY) === 'light' ? 'light' : 'dark'
  } catch {
    return 'dark'
  }
}

export function applyTheme(theme: Theme): void {
  const root = document.documentElement
  if (theme === 'light') root.setAttribute('data-theme', 'light')
  else root.removeAttribute('data-theme')
  document.querySelector('meta[name="theme-color"]')?.setAttribute('content', theme === 'light' ? '#f5f5f8' : '#0b0b0f')
  try {
    localStorage.setItem(KEY, theme)
  } catch {
    // Dann gilt die Wahl nur bis zum Neuladen.
  }
}
