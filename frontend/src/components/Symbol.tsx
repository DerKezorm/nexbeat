/**
 * Die Symbole an einer Stelle, wie in Nexview: 24×24, Strich statt Flaeche,
 * `currentColor`. So nimmt jedes Symbol die Farbe seines Knopfes an.
 */

type Path = { d: string; dot?: boolean; fill?: boolean }

const SYMBOLS = {
  system: [{ d: 'M4 6.5h16M4 12h16M4 17.5h16' }, { d: 'M7.5 6.5v0M7.5 12v0M7.5 17.5v0', dot: true }],
  services: [{ d: 'M9 3v6M15 3v6M6.5 9h11v3a5.5 5.5 0 0 1-11 0V9ZM12 17.5V21' }],
  users: [
    { d: 'M16 20v-1.5a3.5 3.5 0 0 0-3.5-3.5h-4A3.5 3.5 0 0 0 5 18.5V20' },
    { d: 'M10.5 11.5a3.25 3.25 0 1 0 0-6.5 3.25 3.25 0 0 0 0 6.5Z' },
    { d: 'M19 20v-1.5a3.5 3.5 0 0 0-2.6-3.4M15 5.2a3.25 3.25 0 0 1 0 6.1' },
  ],
  quota: [{ d: 'M4 18a8 8 0 1 1 16 0' }, { d: 'M12 18l4.2-4.6' }],
  address: [
    { d: 'M12 20.5a8.5 8.5 0 1 0 0-17 8.5 8.5 0 0 0 0 17Z' },
    { d: 'M3.5 12h17' },
    { d: 'M12 3.5c2.2 2.3 3.4 5.3 3.4 8.5s-1.2 6.2-3.4 8.5c-2.2-2.3-3.4-5.3-3.4-8.5S9.8 5.8 12 3.5Z' },
  ],
  mail: [{ d: 'M4 6.5h16v11H4z' }, { d: 'M4.5 7.2l7.5 5.6 7.5-5.6' }],
  lidarr: [
    { d: 'M12 20.5a8.5 8.5 0 1 0 0-17 8.5 8.5 0 0 0 0 17Z' },
    { d: 'M12 14.5a2.5 2.5 0 1 0 0-5 2.5 2.5 0 0 0 0 5Z', fill: true },
  ],
  sources: [{ d: 'M12 3.5l2.2 5.3 5.8.5-4.4 3.8 1.3 5.6L12 15.8l-4.9 2.9 1.3-5.6L4 9.3l5.8-.5L12 3.5Z' }],
  search: [{ d: 'M10.5 17.5a7 7 0 1 0 0-14 7 7 0 0 0 0 14ZM15.5 15.5 20.5 20.5' }],
  disc: [
    { d: 'M12 20.5a8.5 8.5 0 1 0 0-17 8.5 8.5 0 0 0 0 17Z' },
    { d: 'M12 13.8a1.8 1.8 0 1 0 0-3.6 1.8 1.8 0 0 0 0 3.6Z' },
  ],
  play: [{ d: 'M8 5.5v13l10.5-6.5L8 5.5Z', fill: true }],
  pause: [{ d: 'M7.5 5.5h3v13h-3zM13.5 5.5h3v13h-3z', fill: true }],
  close: [{ d: 'M6 6l12 12M18 6 6 18' }],
  check: [{ d: 'M5 12.5l4.5 4.5L19 7.5' }],
  clock: [{ d: 'M12 20.5a8.5 8.5 0 1 0 0-17 8.5 8.5 0 0 0 0 17Z' }, { d: 'M12 7.5V12l3 2' }],
  sparkle: [
    { d: 'M12 3.5c.6 3.9 2.6 5.9 6.5 6.5-3.9.6-5.9 2.6-6.5 6.5-.6-3.9-2.6-5.9-6.5-6.5 3.9-.6 5.9-2.6 6.5-6.5Z' },
    { d: 'M18.5 16.5c.2 1.3.9 2 2.2 2.2-1.3.2-2 .9-2.2 2.2-.2-1.3-.9-2-2.2-2.2 1.3-.2 2-.9 2.2-2.2Z' },
  ],
  note: [{ d: 'M9 17.5V6l10-2.5V15' }, { d: 'M6.5 20a2.5 2.5 0 1 0 0-5 2.5 2.5 0 0 0 0 5ZM16.5 17.5a2.5 2.5 0 1 0 0-5 2.5 2.5 0 0 0 0 5Z' }],
  arrow: [{ d: 'M5 12h14M13 6l6 6-6 6' }],
  link: [{ d: 'M10 14a4 4 0 0 0 5.7 0l3-3a4 4 0 0 0-5.7-5.7l-1 1M14 10a4 4 0 0 0-5.7 0l-3 3a4 4 0 0 0 5.7 5.7l1-1' }],
  trash: [{ d: 'M5 7h14' }, { d: 'M9.5 7V5h5v2' }, { d: 'M6.5 7l.8 12.1a1 1 0 0 0 1 .9h7.4a1 1 0 0 0 1-.9L17.5 7' }],
  inbox: [{ d: 'M4 13.5 6.5 5h11l2.5 8.5V19H4v-5.5Z' }, { d: 'M4 13.5h4.5l1.5 2.5h4l1.5-2.5H20' }],
} satisfies Record<string, Path[]>

export type SymbolName = keyof typeof SYMBOLS

export function Symbol({ name, className = 'h-4 w-4' }: { name: SymbolName; className?: string }) {
  return (
    <svg viewBox="0 0 24 24" className={className} aria-hidden="true" focusable="false">
      {(SYMBOLS[name] as Path[]).map((path, index) => (
        <path
          key={index}
          d={path.d}
          fill={path.fill ? 'currentColor' : 'none'}
          stroke={path.fill ? 'none' : 'currentColor'}
          strokeWidth={path.dot ? 2.5 : 1.6}
          strokeLinecap="round"
          strokeLinejoin="round"
        />
      ))}
    </svg>
  )
}
