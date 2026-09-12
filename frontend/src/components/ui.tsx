/** Grundbausteine im Nexview-Look, uebernommen und auf nexbeat zugeschnitten. */

import type { ComponentPropsWithRef, InputHTMLAttributes, ReactNode } from 'react'
import { useId } from 'react'
import { useTranslation } from 'react-i18next'

/** Der Stil eines Auswahlfelds, einmal fuer alle. */
export const SELECT_CLASS =
  'rounded-xl border border-ink-700 bg-ink-900 px-4 py-2.5 text-sm text-mist-100 focus:border-accent-500 focus:outline-none disabled:opacity-50'

type ButtonProps = ComponentPropsWithRef<'button'> & {
  variant?: 'primary' | 'ghost'
  loading?: boolean
}

export function Button({ variant = 'primary', loading = false, className = '', children, disabled, ...rest }: ButtonProps) {
  const base =
    'inline-flex items-center justify-center gap-2 rounded-full px-5 py-2.5 text-sm font-semibold ' +
    'transition-colors disabled:cursor-not-allowed disabled:opacity-60'
  const styles =
    variant === 'primary'
      ? 'bg-accent-500 text-white hover:bg-accent-400 shadow-lg shadow-accent-700/25'
      : 'border border-ink-700 bg-ink-850 text-mist-300 hover:bg-ink-800 hover:text-mist-100'
  return (
    <button className={`${base} ${styles} ${className}`} disabled={disabled || loading} {...rest}>
      {loading && <Spinner />}
      {children}
    </button>
  )
}

export function Spinner({ className = 'h-4 w-4' }: { className?: string }) {
  return (
    <svg className={`${className} animate-spin`} viewBox="0 0 24 24" aria-hidden="true">
      <circle cx="12" cy="12" r="9" stroke="currentColor" strokeWidth="3" fill="none" opacity=".25" />
      <path d="M21 12a9 9 0 0 0-9-9" stroke="currentColor" strokeWidth="3" fill="none" strokeLinecap="round" />
    </svg>
  )
}

export function PageLoading() {
  const { t } = useTranslation()
  return (
    <div className="flex min-h-[40vh] items-center justify-center gap-2 text-sm text-mist-600" role="status" aria-live="polite">
      <Spinner />
      <span>{t('common.loading')}</span>
    </div>
  )
}

type FieldProps = InputHTMLAttributes<HTMLInputElement> & {
  label: string
  hint?: ReactNode
}

export function Field({ label, hint, className = '', ...rest }: FieldProps) {
  const id = useId()
  const hintId = hint ? `${id}-hint` : undefined
  return (
    <div className="flex flex-col gap-1.5">
      <label htmlFor={id} className="text-sm font-medium text-mist-300">
        {label}
      </label>
      <input
        id={id}
        aria-describedby={hintId}
        className={
          'rounded-xl border border-ink-700 bg-ink-900 px-4 py-2.5 text-mist-100 ' +
          'placeholder:text-mist-600 transition-colors focus:border-accent-500 focus:outline-none ' +
          className
        }
        {...rest}
      />
      {hint && (
        <p id={hintId} className="text-xs text-mist-500">
          {hint}
        </p>
      )}
    </div>
  )
}

export function ErrorBanner({ message }: { message: string }) {
  return (
    <p role="alert" className="rounded-xl border border-accent-600/50 bg-accent-700/15 px-4 py-3 text-sm text-accent-400">
      {message}
    </p>
  )
}

export function OkBanner({ message }: { message: string }) {
  return (
    <p role="status" className="rounded-xl border border-ok-500/40 bg-ok-500/10 px-4 py-3 text-sm text-ok-500">
      {message}
    </p>
  )
}

export function Card({ children, className = '' }: { children: ReactNode; className?: string }) {
  return (
    <div className={'rounded-2xl border border-ink-700 bg-ink-850/80 p-6 shadow-2xl shadow-black/40 backdrop-blur ' + className}>
      {children}
    </div>
  )
}

/** Ein abgegrenzter Einstellungsbereich: Ueberschrift, Erklaerung, Inhalt in einer Karte. */
export function Section({
  title,
  intro,
  wide = false,
  children,
  className = '',
}: {
  title: string
  intro?: ReactNode
  wide?: boolean
  children: ReactNode
  className?: string
}) {
  return (
    <Card className={'flex flex-col gap-4 ' + className}>
      <div>
        <h2 className="text-lg font-semibold">{title}</h2>
        {intro && <p className="mt-1 text-sm text-mist-500">{intro}</p>}
      </div>
      <div className={'flex flex-col gap-4' + (wide ? '' : ' max-w-3xl')}>{children}</div>
    </Card>
  )
}

/** Eine grosse Zahl mit Beschriftung. */
export function KeyFigure({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div className="rounded-2xl border border-ink-700 bg-ink-850/60 px-4 py-3">
      <p className="text-xs font-medium tracking-wide text-mist-600 uppercase">{label}</p>
      <p className="mt-1 text-3xl font-bold text-mist-100 tabular-nums">{value}</p>
      {hint && <p className="mt-0.5 text-xs text-mist-600">{hint}</p>}
    </div>
  )
}

/** Seitentitel mit rotem Punkt, wie in Nexview. */
export function PageTitle({ children, sub }: { children: ReactNode; sub?: ReactNode }) {
  return (
    <header>
      <h1 className="text-3xl font-bold tracking-tight sm:text-4xl">
        {children}
        <span className="text-accent-500">.</span>
      </h1>
      {sub && <p className="mt-2 max-w-2xl text-sm text-mist-500">{sub}</p>}
    </header>
  )
}

/** Ein Schalter als Kontrollkaestchen, mit Erklaerung darunter. */
export function Toggle({
  label,
  hint,
  checked,
  onChange,
  disabled = false,
}: {
  label: string
  hint?: ReactNode
  checked: boolean
  onChange: (checked: boolean) => void
  disabled?: boolean
}) {
  const id = useId()
  return (
    <div className="flex items-start gap-3">
      <input
        id={id}
        type="checkbox"
        checked={checked}
        disabled={disabled}
        onChange={(event) => onChange(event.target.checked)}
        className="mt-1 h-4 w-4 accent-accent-500"
      />
      <label htmlFor={id} className="flex flex-col gap-0.5">
        <span className="text-sm font-medium text-mist-200">{label}</span>
        {hint && <span className="text-xs text-mist-500">{hint}</span>}
      </label>
    </div>
  )
}
