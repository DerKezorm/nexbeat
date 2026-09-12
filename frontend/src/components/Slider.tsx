import { useRef, useState } from 'react'
import type { ReactNode } from 'react'
import { useTranslation } from 'react-i18next'

/**
 * Waagerechte Leiste mit Pfeilen an den Raendern, wie in Nexview. Die Pfeile
 * erscheinen nur, wenn es in die Richtung etwas zu holen gibt.
 */
export function Slider({ children }: { children: ReactNode }) {
  const { t } = useTranslation()
  const track = useRef<HTMLDivElement | null>(null)
  const [left, setLeft] = useState(false)
  const [right, setRight] = useState(false)

  function measure() {
    const element = track.current
    if (!element) return
    setLeft(element.scrollLeft > 8)
    setRight(element.scrollLeft + element.clientWidth < element.scrollWidth - 8)
  }

  function scroll(direction: -1 | 1) {
    const element = track.current
    if (!element) return
    element.scrollBy({ left: direction * element.clientWidth * 0.85, behavior: 'smooth' })
  }

  return (
    <div className="group/slider relative">
      <div
        ref={(element) => {
          track.current = element
          if (element) requestAnimationFrame(measure)
        }}
        onScroll={measure}
        className="-mx-1 flex snap-x snap-mandatory gap-4 overflow-x-auto scroll-smooth px-1 pb-2 [scrollbar-width:none] [&::-webkit-scrollbar]:hidden"
      >
        {children}
      </div>
      {left && (
        <button
          type="button"
          onClick={() => scroll(-1)}
          aria-label={t('common.scrollLeft')}
          className="absolute top-1/2 -left-2 hidden -translate-y-1/2 rounded-full border border-ink-700 bg-ink-950/90 px-3 py-2 text-mist-200 opacity-0 backdrop-blur transition-opacity group-hover/slider:opacity-100 hover:border-accent-600 sm:block"
        >
          ‹
        </button>
      )}
      {right && (
        <button
          type="button"
          onClick={() => scroll(1)}
          aria-label={t('common.scrollRight')}
          className="absolute top-1/2 -right-2 hidden -translate-y-1/2 rounded-full border border-ink-700 bg-ink-950/90 px-3 py-2 text-mist-200 opacity-0 backdrop-blur transition-opacity group-hover/slider:opacity-100 hover:border-accent-600 sm:block"
        >
          ›
        </button>
      )}
    </div>
  )
}
