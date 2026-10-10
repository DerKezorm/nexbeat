import { useTranslation } from 'react-i18next'

/**
 * Je aktivem Anmeldeanbieter ein Knopf, in der Reihenfolge der Liste: "Mit {{name}} anmelden" auf der Anmeldeseite,
 * "Weiter mit {{name}}" auf der Einladungsseite (dann reist die Einladung mit zum Anbieter).
 *
 * Ein echter Link, kein fetch: Der Anbieter braucht den ganzen Browser, und das Anlauf-Cookie kommt mit der
 * Weiterleitung.
 */
export function ProviderButtons({
  providers,
  invite,
  separator = true,
}: {
  providers: { slug: string; label: string }[]
  invite?: string
  separator?: boolean
}) {
  const { t } = useTranslation()
  if (providers.length === 0) return null
  return (
    <div className="flex flex-col gap-2">
      {separator && (
        <div className="flex items-center gap-3 text-xs text-mist-600">
          <span className="h-px flex-1 bg-ink-700" />
          {t('oidc.login.or')}
          <span className="h-px flex-1 bg-ink-700" />
        </div>
      )}
      {providers.map((provider) => {
        const start = `/api/oidc/${encodeURIComponent(provider.slug)}/start`
        return (
          <a
            key={provider.slug}
            role="button"
            href={invite ? `${start}?invite=${encodeURIComponent(invite)}` : start}
            className="inline-flex w-full items-center justify-center rounded-full border border-ink-700 bg-ink-850 px-5 py-2.5 text-sm font-semibold text-mist-300 transition-colors hover:bg-ink-800 hover:text-mist-100"
          >
            {invite ? t('oidc.invite.button', { name: provider.label }) : t('oidc.login.button', { name: provider.label })}
          </a>
        )
      })}
    </div>
  )
}
