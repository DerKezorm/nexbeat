import { useEffect, useRef, useState } from 'react'
import type { FormEvent } from 'react'
import { useMutation, useQuery } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'

import { api, errorMessage } from '../../api/client'
import type { LidarrOptions, WebhookInfo } from '../../api/types'
import { Symbol } from '../../components/Symbol'
import { Button, Card, ErrorBanner, Field, OkBanner, PageLoading, SELECT_CLASS, Section, Toggle } from '../../components/ui'
import { useSettings } from './useSettings'

function CopyValue({ label, value, secret = false }: { label: string; value: string; secret?: boolean }) {
  const { t } = useTranslation()
  const [shown, setShown] = useState(!secret)
  const [copied, setCopied] = useState(false)
  return (
    <div className="flex flex-col gap-1.5">
      <span className="text-sm font-medium text-mist-300">{label}</span>
      <div className="flex items-center gap-2 rounded-xl border border-ink-700 bg-ink-900 px-4 py-2">
        <code className="min-w-0 flex-1 truncate text-sm text-mist-200">{shown ? value : '••••••••••••'}</code>
        {secret && (
          <button type="button" onClick={() => setShown(!shown)} className="text-xs font-semibold text-mist-500 hover:text-mist-200">
            {shown ? t('common.hide') : t('common.show')}
          </button>
        )}
        <button
          type="button"
          onClick={() => {
            void navigator.clipboard?.writeText(value).then(() => setCopied(true))
          }}
          className="text-xs font-semibold text-accent-500 hover:text-accent-400"
        >
          {copied ? t('common.copied') : t('common.copy')}
        </button>
      </div>
    </div>
  )
}

/**
 * Lidarr verbinden und festlegen, wohin Anfragen gehen.
 *
 * ⚠️ nexbeat liest hier nur Profile und Ordner aus Lidarr. Geaendert wird dort
 * nichts, auch der Webhook wird von Hand eingetragen.
 */
export function AdminLidarrSettings() {
  const { t } = useTranslation()
  const { query, settings, save } = useSettings()
  const filled = useRef(false)
  const [connection, setConnection] = useState({ lidarr_url: '', lidarr_api_key: '' })
  const [target, setTarget] = useState({ root: '', quality: '', metadata: '' })
  const [dryRun, setDryRun] = useState(false)

  useEffect(() => {
    if (!settings || filled.current) return
    filled.current = true
    setConnection({ lidarr_url: settings.lidarr_url, lidarr_api_key: '' })
    setTarget({
      root: settings.lidarr_root_folder,
      quality: settings.lidarr_quality_profile_id ? String(settings.lidarr_quality_profile_id) : '',
      metadata: settings.lidarr_metadata_profile_id ? String(settings.lidarr_metadata_profile_id) : '',
    })
    setDryRun(settings.lidarr_dry_run)
  }, [settings])

  const connected = Boolean(settings?.lidarr_url && settings.lidarr_api_key_set)
  const options = useQuery({
    queryKey: ['lidarr-options', settings?.lidarr_url],
    queryFn: () => api.get<LidarrOptions>('/api/settings/lidarr/options'),
    enabled: connected,
    retry: false,
  })
  const webhook = useQuery({ queryKey: ['webhook'], queryFn: () => api.get<WebhookInfo>('/api/settings/webhook') })
  const selectedProfile = options.data?.metadata_profiles.find((profile) => String(profile.id) === target.metadata)

  const test = useMutation({
    mutationFn: () =>
      api.post<{ ok: boolean; version: string }>('/api/settings/test/lidarr', {
        url: connection.lidarr_url.trim() || null,
        api_key: connection.lidarr_api_key || null,
      }),
  })
  const sync = useMutation({ mutationFn: () => api.post<{ artists: number }>('/api/settings/library/sync') })
  const saveTarget = useMutation({
    mutationFn: () =>
      api.put('/api/settings', {
        lidarr_root_folder: target.root,
        lidarr_quality_profile_id: target.quality,
        lidarr_metadata_profile_id: target.metadata,
      }),
  })
  const saveDryRun = useMutation({ mutationFn: () => api.put('/api/settings', { lidarr_dry_run: dryRun }) })

  // Lidarr ruft nexbeat von aussen an. localhost waere dort Lidarr selbst.
  const webhookBase = settings?.public_url || window.location.origin
  const webhookIsLocal = /^https?:\/\/(localhost|127\.|\[::1\])/i.test(webhookBase)

  if (query.isPending) return <PageLoading />

  return (
    <div className="flex flex-col gap-4">
      <p className="flex items-start gap-2 rounded-xl border border-ink-700 bg-ink-900/70 px-4 py-3 text-sm text-mist-400">
        <Symbol name="check" className="mt-0.5 h-4 w-4 shrink-0 text-ok-500" />
        {t('lidarr.promise')}
      </p>

      <Section title={t('lidarr.connection')} intro={t('lidarr.connectionIntro')}>
        <form
          className="flex flex-col gap-4"
          onSubmit={(event: FormEvent) => {
            event.preventDefault()
            save.mutate(connection)
          }}
        >
          <div className="grid gap-4 sm:grid-cols-2">
            <Field
              label={t('lidarr.url')}
              value={connection.lidarr_url}
              onChange={(event) => setConnection({ ...connection, lidarr_url: event.target.value })}
              placeholder="http://lidarr:8686"
              autoComplete="off"
            />
            <Field
              label={t('lidarr.apiKey')}
              type="password"
              value={connection.lidarr_api_key}
              onChange={(event) => setConnection({ ...connection, lidarr_api_key: event.target.value })}
              placeholder={settings?.lidarr_api_key_set ? settings.lidarr_api_key : ''}
              hint={settings?.lidarr_api_key_set ? t('common.secretSetHint') : t('lidarr.apiKeyHint')}
              autoComplete="new-password"
            />
          </div>
          <div className="flex flex-wrap items-center gap-3">
            <Button type="submit" loading={save.isPending}>
              {t('common.save')}
            </Button>
            <Button type="button" variant="ghost" onClick={() => test.mutate()} loading={test.isPending}>
              {t('lidarr.test')}
            </Button>
            {test.isSuccess && <span className="text-sm text-ok-500">{t('lidarr.testOk', { version: test.data.version })}</span>}
            {test.isError && <span className="text-sm text-bad-500">{errorMessage(test.error)}</span>}
          </div>
          {save.isError && <ErrorBanner message={errorMessage(save.error)} />}
          {save.isSuccess && <OkBanner message={t('common.saved')} />}
        </form>
      </Section>

      <Section title={t('lidarr.target')} intro={t('lidarr.targetIntro')}>
        {!connected ? (
          <p className="text-sm text-mist-500">{t('lidarr.targetNeedsConnection')}</p>
        ) : options.isPending ? (
          <PageLoading />
        ) : options.isError ? (
          <ErrorBanner message={errorMessage(options.error)} />
        ) : (
          <form
            className="flex flex-col gap-4"
            onSubmit={(event: FormEvent) => {
              event.preventDefault()
              saveTarget.mutate()
            }}
          >
            <div className="grid gap-4 sm:grid-cols-3">
              <label className="flex flex-col gap-1.5">
                <span className="text-sm font-medium text-mist-300">{t('lidarr.rootFolder')}</span>
                <select value={target.root} onChange={(event) => setTarget({ ...target, root: event.target.value })} className={SELECT_CLASS}>
                  <option value="">{t('common.choose')}</option>
                  {options.data.root_folders.map((folder) => (
                    <option key={folder.path} value={folder.path}>
                      {folder.path}
                    </option>
                  ))}
                </select>
              </label>
              <label className="flex flex-col gap-1.5">
                <span className="text-sm font-medium text-mist-300">{t('lidarr.qualityProfile')}</span>
                <select value={target.quality} onChange={(event) => setTarget({ ...target, quality: event.target.value })} className={SELECT_CLASS}>
                  <option value="">{t('common.choose')}</option>
                  {options.data.quality_profiles.map((profile) => (
                    <option key={profile.id} value={profile.id}>
                      {profile.name}
                    </option>
                  ))}
                </select>
              </label>
              <label className="flex flex-col gap-1.5">
                <span className="text-sm font-medium text-mist-300">{t('lidarr.metadataProfile')}</span>
                <select value={target.metadata} onChange={(event) => setTarget({ ...target, metadata: event.target.value })} className={SELECT_CLASS}>
                  <option value="">{t('common.choose')}</option>
                  {options.data.metadata_profiles.map((profile) => (
                    <option key={profile.id} value={profile.id}>
                      {profile.name}
                    </option>
                  ))}
                </select>
              </label>
            </div>
            {selectedProfile && (
              <div className="flex flex-col gap-2">
                <p className="text-xs text-mist-400">
                  {t('lidarr.profileAllows', {
                    types: [selectedProfile.primary, selectedProfile.secondary, selectedProfile.statuses]
                      .filter((names) => names.length > 0)
                      .map((names) => names.join(', '))
                      .join(' · '),
                  })}
                </p>
                {!selectedProfile.studio_only && (
                  <p role="note" className="rounded-xl border border-warn-500/40 bg-warn-500/10 px-4 py-3 text-sm text-warn-500">
                    {t('lidarr.profileWide')}
                  </p>
                )}
              </div>
            )}
            <p className="text-xs text-mist-500">{t('lidarr.metadataHint')}</p>
            {saveTarget.isError && <ErrorBanner message={errorMessage(saveTarget.error)} />}
            {saveTarget.isSuccess && <OkBanner message={t('common.saved')} />}
            <div>
              <Button type="submit" loading={saveTarget.isPending} disabled={!target.root || !target.quality || !target.metadata}>
                {t('common.save')}
              </Button>
            </div>
          </form>
        )}
      </Section>

      <Section title={t('lidarr.dryRun')} intro={t('lidarr.dryRunIntro')}>
        <Toggle label={t('lidarr.dryRunToggle')} hint={t('lidarr.dryRunHint')} checked={dryRun} onChange={setDryRun} />
        {saveDryRun.isError && <ErrorBanner message={errorMessage(saveDryRun.error)} />}
        {saveDryRun.isSuccess && <OkBanner message={t('common.saved')} />}
        <div>
          <Button onClick={() => saveDryRun.mutate()} loading={saveDryRun.isPending}>
            {t('common.save')}
          </Button>
        </div>
      </Section>

      <Section title={t('lidarr.library')} intro={t('lidarr.libraryIntro')}>
        <div className="flex flex-wrap items-center gap-3">
          <Button variant="ghost" onClick={() => sync.mutate()} loading={sync.isPending} disabled={!connected}>
            {t('lidarr.syncNow')}
          </Button>
          {sync.isSuccess && <span className="text-sm text-ok-500">{t('lidarr.synced', { count: sync.data.artists })}</span>}
        </div>
        {sync.isError && <ErrorBanner message={errorMessage(sync.error)} />}
      </Section>

      <Card className="flex flex-col gap-4">
        <div>
          <h2 className="text-lg font-semibold">{t('lidarr.webhook')}</h2>
          <p className="mt-1 text-sm text-mist-500">{t('lidarr.webhookIntro')}</p>
        </div>
        {webhook.data && (
          <div className="grid gap-4 lg:grid-cols-3">
            <CopyValue label={t('lidarr.webhookUrl')} value={`${webhookBase}${webhook.data.path}`} />
            <CopyValue label={t('lidarr.webhookUser')} value={webhook.data.username} />
            <CopyValue label={t('lidarr.webhookPassword')} value={webhook.data.password} secret />
          </div>
        )}
        {webhookIsLocal && (
          <p role="note" className="rounded-xl border border-warn-500/40 bg-warn-500/10 px-4 py-3 text-sm text-warn-500">
            {t('lidarr.webhookLocal')}
          </p>
        )}
        <p className="text-xs text-mist-500">{t('lidarr.webhookSteps', { events: webhook.data?.events.join(', ') ?? '' })}</p>
      </Card>
    </div>
  )
}
