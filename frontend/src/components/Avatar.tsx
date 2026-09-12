import { initials, toneFor } from '../lib/avatar'

/** Initialen in fester Farbe je Name. */
export function Avatar({ name, className = 'h-8 w-8' }: { name: string; className?: string }) {
  return (
    <span
      aria-hidden="true"
      className={`${className} flex shrink-0 items-center justify-center rounded-full border border-ink-700 text-xs font-bold ${toneFor(name)}`}
    >
      {initials(name)}
    </span>
  )
}
