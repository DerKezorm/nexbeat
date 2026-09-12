import { useTranslation } from 'react-i18next'

import { errorMessage } from '../api/client'
import { Button } from './ui'

/** Eine Quelle hat gerade nicht geantwortet. Nie als "gibt es nicht" verkleiden. */
export function SectionProblem({ error, retrying, onRetry }: { error: Error | null; retrying: boolean; onRetry: () => void }) {
  const { t } = useTranslation()
  return (
    <div className="flex flex-wrap items-center justify-between gap-3 rounded-2xl border border-dashed border-ink-700 px-5 py-4">
      <p className="text-sm text-mist-400">{errorMessage(error)}</p>
      <Button variant="ghost" onClick={onRetry} loading={retrying}>
        {t('common.tryAgain')}
      </Button>
    </div>
  )
}
