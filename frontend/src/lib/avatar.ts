/** Initialen und eine feste Farbe je Name, fuer Konten und Kuenstler ohne Bild. */

const TONES = [
  'bg-accent-700 text-white',
  'bg-ink-700 text-mist-100',
  'bg-accent-600 text-white',
  'bg-ok-500/30 text-ok-500',
  'bg-warn-500/25 text-warn-500',
] as const

export function initials(name: string): string {
  const parts = name.trim().split(/\s+/).filter(Boolean)
  if (parts.length === 0) return '?'
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase()
  return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase()
}

export function toneFor(name: string): string {
  return TONES[[...name].reduce((sum, char) => sum + char.charCodeAt(0), 0) % TONES.length]
}
