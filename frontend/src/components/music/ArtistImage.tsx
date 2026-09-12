import { useState } from 'react'

import { initials, toneFor } from '../../lib/avatar'

/**
 * Das Bild eines Kuenstlers ueber `/api/images/artist/...`. Gibt es keins,
 * stehen die Initialen da, in fester Farbe je Name.
 */
export function ArtistImage({ src, name, className = '' }: { src?: string | null; name: string; className?: string }) {
  const [failed, setFailed] = useState(false)
  if (!src || failed) {
    return (
      <div
        role="img"
        aria-label={name}
        className={`flex items-center justify-center font-bold ${toneFor(name)} ${className}`}
      >
        <span className="text-[clamp(1rem,4vw,2.5rem)]">{initials(name)}</span>
      </div>
    )
  }
  return <img src={src} alt={name} loading="lazy" onError={() => setFailed(true)} className={'object-cover ' + className} />
}
