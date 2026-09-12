import { useState } from 'react'

import { Symbol } from '../Symbol'

/**
 * Ein Albumcover. Fehlt es beim Cover Art Archive, steht statt eines kaputten
 * Bildes eine ruhige Flaeche mit Platte. Das kommt oft vor und soll nicht wie ein
 * Fehler aussehen.
 */
export function Cover({ src, alt, className = '' }: { src?: string | null; alt: string; className?: string }) {
  const [failed, setFailed] = useState(false)
  if (!src || failed) {
    return (
      <div
        className={
          'flex items-center justify-center bg-linear-to-br from-ink-800 via-ink-900 to-accent-700/30 text-mist-600 ' + className
        }
        aria-hidden={alt ? undefined : true}
        role={alt ? 'img' : undefined}
        aria-label={alt || undefined}
      >
        <Symbol name="disc" className="h-1/3 w-1/3" />
      </div>
    )
  }
  return <img src={src} alt={alt} loading="lazy" onError={() => setFailed(true)} className={'object-cover ' + className} />
}
