import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { api } from '../../api/client'
import type { AppSettings } from '../../api/types'

/** Die Einstellungen und ihr Speichern, fuer alle Karten gleich. */
export function useSettings() {
  const queryClient = useQueryClient()
  const query = useQuery({
    queryKey: ['settings'],
    queryFn: () => api.get<AppSettings>('/api/settings'),
  })
  const save = useMutation({
    // `confirm_address`: bestaetigt die Rueckfrage, wenn die oeffentliche Adresse Rueckleitadressen aendert.
    mutationFn: (patch: Partial<Record<keyof AppSettings | 'confirm_address', unknown>>) =>
      api.put<AppSettings>('/api/settings', patch),
    onSuccess: (data) => {
      queryClient.setQueryData(['settings'], data)
      void queryClient.invalidateQueries({ queryKey: ['discover'] })
    },
  })
  return { query, settings: query.data, save }
}
