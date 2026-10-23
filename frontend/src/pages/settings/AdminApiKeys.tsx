/**
 * Wer in dieser Installation API-Token hat, fuer den Admin. Wie in Nexview.
 *
 * ⚠️ Nur ansehen, nicht widerrufen. Widerrufen kann ein Token nur sein Besitzer. Als Notbremse legt der
 * Admin das Konto still, das sperrt dessen Token mit. Den Token selbst zeigt die Seite nicht, den gibt es
 * nur beim Anlegen; der Anfang reicht zum Wiedererkennen.
 */

import { useQuery } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'

import { api, errorMessage } from '../../api/client'
import { ErrorBanner, Section, Spinner } from '../../components/ui'
import { formatDate } from '../../lib/format'
import type { ApiKey } from '../profile/ApiKeysSection'

type OwnedKey = ApiKey & { user_id: number; username: string }

export function AdminApiKeys() {
  const { t, i18n } = useTranslation()
  const keys = useQuery({ queryKey: ['admin-api-keys'], queryFn: () => api.get<OwnedKey[]>('/api/admin/api-keys') })

  return (
    <Section title={t('adminApiKeys.title')} intro={t('adminApiKeys.intro')} wide>
      {keys.isPending && <Spinner />}
      {keys.isError && <ErrorBanner message={errorMessage(keys.error)} />}
      {keys.data && keys.data.length === 0 && <p className="text-sm text-mist-600">{t('adminApiKeys.empty')}</p>}
      {keys.data && keys.data.length > 0 && (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[36rem] border-collapse text-sm">
            <thead>
              <tr className="border-b border-ink-700 text-left text-xs tracking-wide text-mist-600 uppercase">
                <th className="py-2 pr-4 font-medium">{t('adminApiKeys.owner')}</th>
                <th className="py-2 pr-4 font-medium">{t('adminApiKeys.name')}</th>
                <th className="py-2 pr-4 font-medium">{t('adminApiKeys.created')}</th>
                <th className="py-2 font-medium">{t('adminApiKeys.lastUsed')}</th>
              </tr>
            </thead>
            <tbody>
              {keys.data.map((key) => (
                <tr key={key.id} className="border-b border-ink-800 last:border-0">
                  <td className="py-2.5 pr-4 text-mist-100">@{key.username}</td>
                  <td className="py-2.5 pr-4">
                    <span className="text-mist-200">{key.name}</span>
                    {key.read_only && (
                      <span className="ml-2 rounded-full bg-ink-800 px-2 py-0.5 text-xs text-mist-500">{t('apiKeys.readOnly')}</span>
                    )}
                    <span className="block font-mono text-xs text-mist-600">{key.preview}…</span>
                  </td>
                  <td className="py-2.5 pr-4 text-mist-500">{formatDate(key.created_at, i18n.language)}</td>
                  <td className="py-2.5 text-mist-500">
                    {key.last_used_at ? formatDate(key.last_used_at, i18n.language) : t('apiKeys.neverUsed')}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Section>
  )
}
