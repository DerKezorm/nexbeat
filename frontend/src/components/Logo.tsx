/**
 * nexbeat-Zeichen: eine Pulslinie mit rotem Ausschlag und Punkt am Ende. Hell auf weißer Kachel, dunkel auf dunkler;
 * die Farben sind `--nb-logo-*` in styles/index.css (Quelle nexapps/icons-vergleich/neu.py, wie public/logo.svg).
 */
export function Logo({ className = 'h-8 w-8', withWordmark = false }: { className?: string; withWordmark?: boolean }) {
  // userSpaceOnUse: der Verlauf läuft über das ganze Zeichen, statt je Strich neu zu beginnen.
  const mark = (
    <svg viewBox="0 0 64 64" className={className} aria-hidden="true">
      <defs>
        <linearGradient id="nexbeat-mark" gradientUnits="userSpaceOnUse" x1="10" y1="10" x2="54" y2="54">
          <stop offset="0" style={{ stopColor: 'var(--nb-logo-verlauf-1)' }} />
          <stop offset=".5" style={{ stopColor: 'var(--nb-logo-verlauf-2)' }} />
          <stop offset="1" style={{ stopColor: 'var(--nb-logo-verlauf-3)' }} />
        </linearGradient>
      </defs>
      <rect x="2" y="2" width="60" height="60" rx="16" style={{ fill: 'var(--nb-logo-grund)' }} />
      <rect
        x="2.75"
        y="2.75"
        width="58.5"
        height="58.5"
        rx="15.3"
        fill="none"
        strokeWidth="1.5"
        style={{ stroke: 'var(--nb-logo-rand)', strokeOpacity: 'var(--nb-logo-rand-deckung)' }}
      />
      <path
        d="M10 33h9l4.5-11 7 22 6.5-17 4 6H54"
        fill="none"
        stroke="url(#nexbeat-mark)"
        strokeWidth="4.4"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <path d="M23.5 22 30.5 44" strokeWidth="4.4" strokeLinecap="round" style={{ stroke: 'var(--nb-logo-akzent)' }} />
      <circle cx="54" cy="33" r="3.6" strokeWidth="1.8" style={{ fill: 'var(--nb-logo-akzent)', stroke: 'var(--nb-logo-grund)' }} />
    </svg>
  )
  if (!withWordmark) return mark
  return (
    <span className="flex items-center gap-2.5">
      {mark}
      <span className="hidden text-lg font-bold tracking-tight sm:inline">
        NEX<span className="text-accent-500">BEAT</span>
      </span>
    </span>
  )
}
