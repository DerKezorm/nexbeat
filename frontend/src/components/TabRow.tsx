/**
 * Eine Reihe Reiter, oben wie unten gleich. Wie `Reiterreihe` in Nexview: Die
 * Seiten geben nur her, was darin steht, das Aussehen entscheidet dieses Bauteil.
 */

import { Symbol, type SymbolName } from './Symbol'

export type Tab<T extends string> = {
  value: T
  label: string
  symbol?: SymbolName
}

export function TabRow<T extends string>({
  tabs,
  active,
  onChange,
  sub = false,
  label,
}: {
  tabs: Tab<T>[]
  active: T
  onChange: (value: T) => void
  /** Untergeordnete Reihe mit Strich links, der sie an die Reihe darueber bindet. */
  sub?: boolean
  label?: string
}) {
  return (
    <div
      className={'flex flex-wrap items-center gap-2 ' + (sub ? 'border-l-2 border-accent-500/40 pl-4' : '')}
      role="tablist"
      aria-label={label}
    >
      {tabs.map((tab) => {
        const selected = active === tab.value
        return (
          <button
            key={tab.value}
            type="button"
            role="tab"
            aria-selected={selected}
            onClick={() => onChange(tab.value)}
            className={
              'inline-flex items-center gap-2 rounded-full border text-sm font-medium transition-colors ' +
              (sub ? 'px-3.5 py-1.5 ' : 'px-4 py-2 ') +
              (selected
                ? 'border-accent-500/60 bg-accent-500/15 text-accent-400'
                : 'border-ink-700 bg-ink-900 text-mist-500 hover:text-mist-100')
            }
          >
            {tab.symbol && <Symbol name={tab.symbol} />}
            {tab.label}
          </button>
        )
      })}
    </div>
  )
}
