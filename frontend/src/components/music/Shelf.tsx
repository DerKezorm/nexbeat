import type { ReactNode } from 'react'

import { Slider } from '../Slider'

/** Eine Reihe mit Ueberschrift, wie die Regale in Nexview. */
export function Shelf({
  title,
  hint,
  action,
  children,
  delay = 0,
}: {
  title: ReactNode
  hint?: ReactNode
  action?: ReactNode
  children: ReactNode
  delay?: number
}) {
  return (
    <section className="flex flex-col gap-3 animate-nv-rise" style={{ animationDelay: `${delay}ms` }}>
      <header className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
        <div>
          <h2 className="text-xl font-bold tracking-tight">{title}</h2>
          {hint && <p className="mt-0.5 text-sm text-mist-500">{hint}</p>}
        </div>
        {action}
      </header>
      <Slider>{children}</Slider>
    </section>
  )
}

export function ShelfSkeleton({ round = false }: { round?: boolean }) {
  return (
    <div className="flex flex-col gap-3">
      <div className="h-6 w-56 animate-pulse rounded bg-ink-800" />
      <div className="flex gap-4 overflow-hidden">
        {Array.from({ length: 7 }, (_, index) => (
          <div key={index} className="flex w-36 shrink-0 flex-col gap-2">
            <div className={'aspect-square animate-pulse bg-ink-800 ' + (round ? 'rounded-full' : 'rounded-xl')} />
            <div className="h-3 w-3/4 animate-pulse rounded bg-ink-800" />
          </div>
        ))}
      </div>
    </div>
  )
}
