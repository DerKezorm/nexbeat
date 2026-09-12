import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useSearchParams } from 'react-router-dom'

import { TabRow, type Tab } from '../components/TabRow'
import { PageTitle } from '../components/ui'
import { AdminAddressSettings } from './settings/AdminAddressSettings'
import { AdminLidarrSettings } from './settings/AdminLidarrSettings'
import { AdminMailSettings } from './settings/AdminMailSettings'
import { AdminQuotaSettings } from './settings/AdminQuotaSettings'
import { AdminSourcesSettings } from './settings/AdminSourcesSettings'
import { AdminUsersSettings } from './settings/AdminUsersSettings'

type TabKey = 'address' | 'mail' | 'lidarr' | 'sources' | 'users' | 'quota'

/** Was unter "System" liegt: die Anlage selbst, nicht der Alltag. */
const SYSTEM: Tab<TabKey>[] = [
  { value: 'address', label: 'settings.tabAddress', symbol: 'address' },
  { value: 'mail', label: 'settings.tabMail', symbol: 'mail' },
]

/** Was unter "Dienste" liegt: wohin nexbeat sich verbindet. */
const SERVICES: Tab<TabKey>[] = [
  { value: 'lidarr', label: 'settings.tabLidarr', symbol: 'lidarr' },
  { value: 'sources', label: 'settings.tabSources', symbol: 'sources' },
]

/**
 * ⚠️ Deutsche Woerter in der Adresse, englische Werte im Code, wie in Nexview.
 * Die Namen sind eine Zusage: Verweise wie `?reiter=lidarr` stehen in Seiten.
 */
const FROM_ADDRESS: Record<string, TabKey> = {
  adresse: 'address',
  mail: 'mail',
  lidarr: 'lidarr',
  quellen: 'sources',
  benutzer: 'users',
  kontingente: 'quota',
}

/** Einstellungen des Admins, im Aufbau von Nexview: Reiter oben, eine zweite Reihe nur wo noetig. */
export function SettingsPage() {
  const { t } = useTranslation()
  const [params, setParams] = useSearchParams()
  const [tab, setTab] = useState<TabKey>(FROM_ADDRESS[params.get('reiter') ?? ''] ?? 'address')

  function change(next: TabKey) {
    setTab(next)
    if (params.has('reiter')) setParams({}, { replace: true })
  }

  const inSystem = SYSTEM.some((entry) => entry.value === tab)
  const inServices = SERVICES.some((entry) => entry.value === tab)
  const topTabs: Tab<TabKey>[] = [
    { value: 'address', label: t('settings.tabSystem'), symbol: 'system' },
    { value: 'lidarr', label: t('settings.tabServices'), symbol: 'services' },
    { value: 'users', label: t('settings.tabUsers'), symbol: 'users' },
    { value: 'quota', label: t('settings.tabQuota'), symbol: 'quota' },
  ]

  return (
    <div className="flex flex-col gap-6">
      <PageTitle>{t('settings.title')}</PageTitle>
      <TabRow tabs={topTabs} active={inSystem ? 'address' : inServices ? 'lidarr' : tab} onChange={change} />
      {inSystem && (
        <TabRow sub label={t('settings.tabSystem')} tabs={SYSTEM.map((entry) => ({ ...entry, label: t(entry.label) }))} active={tab} onChange={change} />
      )}
      {inServices && (
        <TabRow sub label={t('settings.tabServices')} tabs={SERVICES.map((entry) => ({ ...entry, label: t(entry.label) }))} active={tab} onChange={change} />
      )}

      {tab === 'address' && <AdminAddressSettings />}
      {tab === 'mail' && <AdminMailSettings />}
      {tab === 'lidarr' && <AdminLidarrSettings />}
      {tab === 'sources' && <AdminSourcesSettings />}
      {tab === 'users' && <AdminUsersSettings />}
      {tab === 'quota' && <AdminQuotaSettings />}
    </div>
  )
}
