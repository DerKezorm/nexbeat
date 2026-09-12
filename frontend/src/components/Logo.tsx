/** nexbeat-Zeichen: ein Pulsschlag im Rotverlauf, im Rahmen des Nexview-Zeichens. */
export function Logo({ className = 'h-8 w-8', withWordmark = false }: { className?: string; withWordmark?: boolean }) {
  const mark = (
    <svg viewBox="0 0 64 64" className={className} aria-hidden="true">
      <defs>
        <linearGradient id="nexbeat-mark" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0%" stopColor="#ff3b4e" />
          <stop offset="55%" stopColor="#e11d2f" />
          <stop offset="100%" stopColor="#8f0f1c" />
        </linearGradient>
      </defs>
      <rect x="2" y="2" width="60" height="60" rx="16" fill="#141019" />
      <rect x="2" y="2" width="60" height="60" rx="16" fill="none" stroke="url(#nexbeat-mark)" strokeWidth="2.5" strokeOpacity=".55" />
      <path
        d="M11 33h8l4.5-11 7 22 6.5-17 4 6H53"
        fill="none"
        stroke="url(#nexbeat-mark)"
        strokeWidth="3.6"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
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
