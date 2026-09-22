import { useState } from 'react'
import type { FormEvent } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'

import { api, errorMessage, storedError } from '../../api/client'
import type { Delivery, Invitation, InvitationCreated, Role, User } from '../../api/types'
import { useAuth } from '../../auth/useAuth'
import { Avatar } from '../../components/Avatar'
import { ConfirmDialog } from '../../components/ConfirmDialog'
import { Button, Card, ErrorBanner, Field, OkBanner, PageLoading, SELECT_CLASS, Toggle } from '../../components/ui'
import { formatDate } from '../../lib/format'
import { useTarget } from '../../lib/target'

type QuotaMode = 'default' | 'unlimited' | 'custom'

function DeliveryResult({ delivery, email }: { delivery: Delivery; email?: string }) {
  const { t } = useTranslation()
  const [copied, setCopied] = useState(false)
  if (delivery.sent) return <OkBanner message={t('users.sent', { email })} />
  return (
    <div className="flex flex-col gap-2 rounded-xl border border-warn-500/40 bg-warn-500/10 px-4 py-3 text-sm">
      <p className="text-warn-500">{t('users.manualLink', { reason: storedError(delivery.error_code) ?? '' })}</p>
      <div className="flex items-center gap-2 rounded-lg border border-ink-700 bg-ink-900 px-3 py-2">
        <code className="min-w-0 flex-1 truncate text-xs text-mist-200">{delivery.manual_link}</code>
        <button
          type="button"
          onClick={() => void navigator.clipboard?.writeText(delivery.manual_link ?? '').then(() => setCopied(true))}
          className="text-xs font-semibold text-accent-500 hover:text-accent-400"
        >
          {copied ? t('common.copied') : t('common.copy')}
        </button>
      </div>
    </div>
  )
}

function UserEditor({ user, onDone }: { user: User; onDone: () => void }) {
  const { t } = useTranslation()
  const target = useTarget()
  const queryClient = useQueryClient()
  const [role, setRole] = useState<Role>(user.role)
  const [active, setActive] = useState(user.is_active)
  const [approval, setApproval] = useState(user.requires_approval)
  const [mode, setMode] = useState<QuotaMode>(user.quota_limit === null ? 'default' : user.quota_limit < 0 ? 'unlimited' : 'custom')
  const [amount, setAmount] = useState(user.quota_limit !== null && user.quota_limit >= 0 ? String(user.quota_limit) : '5')

  const save = useMutation({
    mutationFn: () =>
      api.patch<User>(`/api/users/${user.id}`, {
        role,
        is_active: active,
        requires_approval: approval,
        quota: mode === 'custom' ? Number(amount) : mode,
      }),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['users'] })
      onDone()
    },
  })

  return (
    <form
      className="mt-4 flex flex-col gap-4 border-t border-ink-700 pt-4"
      onSubmit={(event: FormEvent) => {
        event.preventDefault()
        save.mutate()
      }}
    >
      <div className="grid gap-4 sm:grid-cols-3">
        <label className="flex flex-col gap-1.5">
          <span className="text-sm font-medium text-mist-300">{t('users.role')}</span>
          <select value={role} onChange={(event) => setRole(event.target.value as Role)} className={SELECT_CLASS}>
            <option value="user">{t('users.roleUser')}</option>
            <option value="admin">{t('users.roleAdmin')}</option>
          </select>
        </label>
        <label className="flex flex-col gap-1.5">
          <span className="text-sm font-medium text-mist-300">{t('users.quota')}</span>
          <select value={mode} onChange={(event) => setMode(event.target.value as QuotaMode)} className={SELECT_CLASS}>
            <option value="default">{t('users.quotaDefault')}</option>
            <option value="unlimited">{t('users.quotaUnlimited')}</option>
            <option value="custom">{t('users.quotaCustom')}</option>
          </select>
        </label>
        {mode === 'custom' && (
          <Field label={t('users.quotaAmount')} type="number" min={0} max={10000} value={amount} onChange={(event) => setAmount(event.target.value)} />
        )}
      </div>
      <Toggle label={t('users.active')} hint={t('users.activeHint')} checked={active} onChange={setActive} />
      <Toggle label={t('users.requiresApproval')} hint={t('users.requiresApprovalHint', { target })} checked={approval} onChange={setApproval} />
      {save.isError && <ErrorBanner message={errorMessage(save.error)} />}
      <div className="flex flex-wrap gap-2">
        <Button type="submit" loading={save.isPending}>
          {t('common.save')}
        </Button>
        <Button type="button" variant="ghost" onClick={onDone}>
          {t('common.cancel')}
        </Button>
      </div>
    </form>
  )
}

/** Benutzer im Aufbau von Nexview: Einladen oben, offene Einladungen, dann Karten nach Rolle. */
export function AdminUsersSettings() {
  const { t, i18n } = useTranslation()
  const target = useTarget()
  const { user: me } = useAuth()
  const queryClient = useQueryClient()
  const [invite, setInvite] = useState({ email: '', role: 'user' as Role })
  const [editing, setEditing] = useState<number | null>(null)
  const [deleting, setDeleting] = useState<User | null>(null)
  const [linkFor, setLinkFor] = useState<{ id: number; delivery: Delivery } | null>(null)

  const users = useQuery({ queryKey: ['users'], queryFn: () => api.get<User[]>('/api/users') })
  const invitations = useQuery({ queryKey: ['invitations'], queryFn: () => api.get<Invitation[]>('/api/users/invitations') })

  const createInvite = useMutation({
    mutationFn: () => api.post<InvitationCreated>('/api/users/invitations', invite),
    onSuccess: async () => {
      setInvite({ email: '', role: 'user' })
      await queryClient.invalidateQueries({ queryKey: ['invitations'] })
    },
  })
  const withdraw = useMutation({
    mutationFn: (id: number) => api.delete<void>(`/api/users/invitations/${id}`),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['invitations'] }),
  })
  const passwordLink = useMutation({
    mutationFn: (id: number) => api.post<Delivery>(`/api/users/${id}/password-reset`),
    onSuccess: (delivery, id) => setLinkFor({ id, delivery }),
  })
  const resetQuota = useMutation({
    mutationFn: (id: number) => api.post<User>(`/api/users/${id}/quota/reset`),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['users'] }),
  })
  const remove = useMutation({
    mutationFn: (id: number) => api.delete<void>(`/api/users/${id}`),
    onSuccess: async () => {
      setDeleting(null)
      await queryClient.invalidateQueries({ queryKey: ['users'] })
    },
  })

  if (users.isPending) return <PageLoading />
  if (users.isError) return <ErrorBanner message={errorMessage(users.error)} />

  const groups: { role: Role; title: string }[] = [
    { role: 'admin', title: t('users.groupAdmins') },
    { role: 'user', title: t('users.groupUsers') },
  ]

  return (
    <div className="flex flex-col gap-6">
      <Card className="flex flex-col gap-4">
        <div>
          <h2 className="text-lg font-semibold">{t('users.inviteTitle')}</h2>
          <p className="mt-1 text-sm text-mist-500">{t('users.inviteIntro')}</p>
        </div>
        <form
          className="flex flex-wrap items-end gap-3"
          onSubmit={(event: FormEvent) => {
            event.preventDefault()
            createInvite.mutate()
          }}
        >
          <div className="min-w-64 flex-1">
            <Field label={t('users.email')} type="email" value={invite.email} onChange={(event) => setInvite({ ...invite, email: event.target.value })} placeholder="name@example.com" required />
          </div>
          <label className="flex flex-col gap-1.5">
            <span className="text-sm font-medium text-mist-300">{t('users.role')}</span>
            <select value={invite.role} onChange={(event) => setInvite({ ...invite, role: event.target.value as Role })} className={SELECT_CLASS}>
              <option value="user">{t('users.roleUser')}</option>
              <option value="admin">{t('users.roleAdmin')}</option>
            </select>
          </label>
          <Button type="submit" loading={createInvite.isPending} className="mb-0.5">
            {t('users.invite')}
          </Button>
        </form>
        {createInvite.isError && <ErrorBanner message={errorMessage(createInvite.error)} />}
        {createInvite.isSuccess && <DeliveryResult delivery={createInvite.data.delivery} email={createInvite.data.invitation.email} />}

        {invitations.data && invitations.data.length > 0 && (
          <div className="flex flex-col gap-2 border-t border-ink-700 pt-4">
            <h3 className="text-xs font-semibold tracking-wide text-mist-600 uppercase">{t('users.openInvitations')}</h3>
            <ul className="flex flex-col gap-2">
              {invitations.data.map((item) => (
                <li key={item.id} className="flex flex-wrap items-center gap-3 rounded-xl border border-ink-700 bg-ink-900/60 px-4 py-2 text-sm">
                  <span className="min-w-0 flex-1 truncate text-mist-200">{item.email}</span>
                  <span className="text-xs text-mist-500">{t(item.role === 'admin' ? 'users.roleAdmin' : 'users.roleUser')}</span>
                  <span className="text-xs text-mist-600">{t('users.expires', { date: formatDate(item.expires_at, i18n.language) })}</span>
                  <Button variant="ghost" className="px-3 py-1 text-xs" loading={withdraw.isPending && withdraw.variables === item.id} onClick={() => withdraw.mutate(item.id)}>
                    {t('users.withdraw')}
                  </Button>
                </li>
              ))}
            </ul>
          </div>
        )}
      </Card>

      {groups.map((group) => {
        const members = users.data.filter((user) => user.role === group.role)
        if (members.length === 0) return null
        return (
          <section key={group.role} className="flex flex-col gap-3">
            <h3 className="text-xs font-semibold tracking-wide text-mist-600 uppercase">
              {group.title} · {members.length}
            </h3>
            {members.map((user) => {
              const name = user.display_name || user.username
              const quota = user.quota
              return (
                <Card key={user.id} className="p-4">
                  <div className="flex flex-wrap items-center gap-4">
                    <Avatar name={name} className="h-11 w-11" />
                    <div className="min-w-0 flex-1">
                      <p className="flex flex-wrap items-center gap-2 font-semibold">
                        {name}
                        {!user.is_active && <span className="rounded-full bg-bad-500/15 px-2 py-0.5 text-[11px] text-bad-500">{t('users.inactive')}</span>}
                        {user.requires_approval && <span className="rounded-full bg-warn-500/15 px-2 py-0.5 text-[11px] text-warn-500">{t('users.approvalBadge')}</span>}
                      </p>
                      <p className="truncate text-xs text-mist-500">
                        @{user.username} · {user.email}
                      </p>
                    </div>
                    <div className="text-right">
                      <p className="text-sm font-semibold tabular-nums">{quota.limit === null ? '∞' : `${quota.used}/${quota.limit}`}</p>
                      <p className="text-[11px] text-mist-600">{t(`quota.period_${quota.period}`)}</p>
                    </div>
                    <Button variant="ghost" className="px-4 py-1.5 text-xs" onClick={() => setEditing(editing === user.id ? null : user.id)}>
                      {editing === user.id ? t('common.close') : t('users.edit')}
                    </Button>
                  </div>
                  {editing === user.id && (
                    <>
                      <UserEditor user={user} onDone={() => setEditing(null)} />
                      <div className="mt-4 flex flex-wrap gap-2 border-t border-ink-700 pt-4">
                        <Button variant="ghost" className="text-xs" loading={passwordLink.isPending} onClick={() => passwordLink.mutate(user.id)}>
                          {t('users.passwordLink')}
                        </Button>
                        <Button variant="ghost" className="text-xs" loading={resetQuota.isPending} onClick={() => resetQuota.mutate(user.id)}>
                          {t('users.resetQuota')}
                        </Button>
                        {user.id !== me?.id && (
                          <Button
                            variant="ghost"
                            className="border-bad-500/40 text-xs text-bad-500 hover:bg-bad-500/10 hover:text-bad-500"
                            onClick={() => setDeleting(user)}
                          >
                            {t('users.delete')}
                          </Button>
                        )}
                      </div>
                      {linkFor?.id === user.id && (
                        <div className="mt-3">
                          <DeliveryResult delivery={linkFor.delivery} email={user.email} />
                        </div>
                      )}
                      {passwordLink.isError && <ErrorBanner message={errorMessage(passwordLink.error)} />}
                    </>
                  )}
                </Card>
              )
            })}
          </section>
        )
      })}

      <ConfirmDialog
        open={deleting !== null}
        title={t('users.deleteTitle')}
        description={t('users.deleteText', { name: deleting?.display_name || deleting?.username, target })}
        confirmLabel={t('users.delete')}
        loading={remove.isPending}
        error={remove.isError ? errorMessage(remove.error) : null}
        onCancel={() => setDeleting(null)}
        onConfirm={() => deleting && remove.mutate(deleting.id)}
      />
    </div>
  )
}
