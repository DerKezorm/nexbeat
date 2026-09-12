import type { ReactNode } from 'react'

import { Logo } from './Logo'
import { LanguageSwitcher, ThemeSwitcher } from './Switchers'

/** Der Rahmen der Seiten ohne Anmeldung: Zeichen, Schalter, eine Karte in der Mitte. */
export function AuthFrame({ children, wide = false }: { children: ReactNode; wide?: boolean }) {
  return (
    <div className="nv-glow flex min-h-dvh items-center justify-center px-4 py-10">
      <div className={'relative z-10 w-full ' + (wide ? 'max-w-md' : 'max-w-sm')}>
        <div className="mb-6 flex items-center justify-between">
          <Logo withWordmark />
          <div className="flex items-center gap-2">
            <ThemeSwitcher />
            <LanguageSwitcher />
          </div>
        </div>
        {children}
      </div>
    </div>
  )
}
