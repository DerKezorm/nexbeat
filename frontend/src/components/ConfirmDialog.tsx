import { useEffect, useRef } from 'react'
import { createPortal } from 'react-dom'
import type { ReactNode } from 'react'
import { useTranslation } from 'react-i18next'

import { Button } from './ui'

/**
 * Rueckfrage im Nexview-Stil statt des Browser-Popups. Escape und ein Klick
 * daneben brechen ab, "Abbrechen" ist der eine Notausgang.
 */
export function ConfirmDialog({
  open,
  title,
  description,
  error,
  confirmLabel,
  onConfirm,
  onCancel,
  loading = false,
  children,
}: {
  open: boolean
  title: string
  description: ReactNode
  error?: string | null
  confirmLabel: string
  onConfirm: () => void
  onCancel: () => void
  loading?: boolean
  children?: ReactNode
}) {
  const { t } = useTranslation()
  const confirmRef = useRef<HTMLButtonElement>(null)

  useEffect(() => {
    if (!open) return
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === 'Escape') onCancel()
    }
    document.addEventListener('keydown', onKeyDown)
    const previous = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    confirmRef.current?.focus()
    return () => {
      document.removeEventListener('keydown', onKeyDown)
      document.body.style.overflow = previous
    }
  }, [open, onCancel])

  if (!open) return null

  return createPortal(
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-scrim p-4 backdrop-blur-sm"
      role="dialog"
      aria-modal="true"
      aria-label={title}
      onClick={(event) => {
        if (event.target === event.currentTarget) onCancel()
      }}
    >
      <div className="max-h-[85vh] w-full max-w-md overflow-y-auto rounded-2xl border border-ink-700 bg-ink-850 p-6 shadow-2xl shadow-black/60">
        <h2 className="text-lg font-bold tracking-tight">{title}</h2>
        <div className="mt-2 text-sm leading-relaxed text-mist-300">{description}</div>
        {children}
        {error && (
          <p className="mt-3 rounded-xl border border-bad-500/40 bg-bad-500/10 px-3 py-2 text-sm text-bad-500" role="alert">
            {error}
          </p>
        )}
        <div className="mt-6 flex flex-wrap justify-end gap-2">
          <Button variant="ghost" onClick={onCancel} disabled={loading}>
            {t('common.cancel')}
          </Button>
          <Button ref={confirmRef} onClick={onConfirm} loading={loading}>
            {confirmLabel}
          </Button>
        </div>
      </div>
    </div>,
    document.body,
  )
}
