import { useState } from 'react'
import { useTranslation } from 'react-i18next'

import { api } from '../api/client'
import type { Me } from '../api/types'
import { useAuth } from '../auth/useAuth'
import { entryFor, latestVersion, unseen } from '../lib/whatsnew'
import { WhatsNewDialog } from './WhatsNewDialog'

/**
 * Nach einem Update einmal "Was ist neu" zeigen, jedem Konto (entschieden am 22.09.2026).
 *
 * ⚠️ Das Fenster geht sofort zu, der Vermerk an den Server folgt. In nexdeck wartete jeder Ausgang auf die Antwort,
 * und ohne Server oder mit abgelaufener Sitzung liess sich das Fenster nicht schliessen. Scheitert der Vermerk, kommt
 * das Fenster beim naechsten Besuch wieder.
 */
export function WhatsNewAfterUpdate() {
  const { i18n } = useTranslation()
  const { user, updateUser, config } = useAuth()
  const [closed, setClosed] = useState(false)
  const version = latestVersion(config?.version)
  if (closed || !user || !version || !unseen(user.seen_version, version)) return null
  const entry = entryFor(version, i18n.language)
  if (!entry) return null

  function close() {
    setClosed(true)
    api
      .patch<Me>('/api/auth/me', { seen_version: version })
      .then(updateUser)
      .catch(() => undefined)
  }

  return <WhatsNewDialog version={version} entry={entry} isAdmin={user.is_admin} onClose={close} />
}
