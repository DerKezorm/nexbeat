import { useTranslation } from 'react-i18next'

import type { AddressQuestionValues } from '../lib/addressQuestion'

/** Die Rueckfrage vor einer neuen oeffentlichen Adresse, in den Worten des Anmeldemoduls. */
export function AddressQuestion({ question }: { question: AddressQuestionValues }) {
  const { t } = useTranslation()
  return (
    <span className="flex flex-col gap-2" data-testid="address-question">
      {question.count > 0 && <span>{t('oidc.admin.addressChangeConfirm', { address: question.address })}</span>}
      {question.hand > 0 && <span>{t('oidc.admin.addressChangeHand', { count: question.hand })}</span>}
    </span>
  )
}
