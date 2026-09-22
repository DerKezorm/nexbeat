import { useTranslation } from 'react-i18next'

import { useAuth } from '../auth/useAuth'

/**
 * Der Name des Programms, an das Anfragen gehen, fuer Saetze wie "{{target}} sucht".
 * ARR-Modus: Lidarr, NEX-Modus: nexcrate, nichts gewaehlt: "Lidarr oder nexcrate".
 */
export function useTarget(): string {
  const { t } = useTranslation()
  const { user } = useAuth()
  if (user?.request_target === 'nexcrate') return 'nexcrate'
  if (user?.request_target === 'lidarr') return 'Lidarr'
  return t('common.targetEither')
}
