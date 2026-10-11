/**
 * nexoidc in the browser: the fixed codes and names the server sends, the keys of their texts, and the slug the
 * provider form suggests. No framework, no app parts: the cards, buttons and dialogs are the app's own (Bauplan 04),
 * the words come from `oidc.de.json` and `oidc.en.json` next to this file.
 *
 * Copied unchanged into every app by `bauplaene/oidc/tools/sync.py`; changed only in `bauplaene/oidc`.
 *
 * The wording files use i18next's `{{app}}` for the name of the app and `{{slug}}` for the slug the authentik button
 * gives the app's application (since 1.0.12). Set both once through `oidcVariables`, for example
 * `i18n.init({ interpolation: { defaultVariables: oidcVariables('nexlore') } })`, and merge the files into the app's
 * resources under the same keys (`oidc.…`) through `oidcWording` (since 1.0.9; it picks the sentences of apps with
 * one account and, since 1.0.12, of apps without invitations).
 */

/** The error codes of Bauplan 02; each has a sentence under `oidc.error.<code>`. Same order as `errors.CODES`. */
export const OIDC_ERROR_CODES = [
  'oidc_not_configured',
  'oidc_provider_unreachable',
  'oidc_provider_invalid',
  'oidc_issuer_mismatch',
  'oidc_state_mismatch',
  'oidc_provider_error',
  'oidc_token_refused',
  'oidc_token_invalid',
  'oidc_no_signing_key',
  'oidc_no_account',
  'oidc_subject_taken',
  'oidc_only_account',
  'oidc_link_mismatch',
  'invite_invalid',
  'account_blocked',
  'too_many_attempts',
] as const

/** Problems with the provider form, under `oidc.formError.<code>`. Same order as `errors.FORM_CODES`. */
export const OIDC_FORM_CODES = [
  'slug_invalid',
  'slug_taken',
  'label_required',
  'issuer_invalid',
  'client_id_required',
  'client_secret_invalid',
  'scopes_invalid',
  'provider_managed',
  'provider_unknown',
] as const

/** The steps of the authentik button in their order; `binding` only in apps with one account. */
export const AUTHENTIK_STEPS = ['reached', 'signingKey', 'mapping', 'provider', 'application', 'filled'] as const
export const AUTHENTIK_STEP_BINDING = 'binding'
/**
 * Why a step failed, under `oidc.authentik.why.<reason>` (with `{{status}}`; `issuer_change` with `{{count}}`).
 * `public_url_needed` (since 1.0.10): the app has no public address and none was confirmed; the card shows its
 * suggestion (`authentikProposal`) and runs the button again with `public_url`.
 */
export const AUTHENTIK_REASONS = [
  'unreachable',
  'unusable',
  'token',
  'malformed',
  'answered',
  'slug',
  'coupled',
  'issuer_change',
  'public_url_needed',
] as const

export type OidcErrorCode = (typeof OIDC_ERROR_CODES)[number]

/** The text key of an error code from `?error=`, or null for anything else (never show a raw code from the address). */
export function oidcErrorKey(code: string | null | undefined): string | null {
  return code && (OIDC_ERROR_CODES as readonly string[]).includes(code) ? `oidc.error.${code}` : null
}

/** The text key of a form problem, or null. */
export function oidcFormErrorKey(code: string | null | undefined): string | null {
  return code && (OIDC_FORM_CODES as readonly string[]).includes(code) ? `oidc.formError.${code}` : null
}

/** The text key of a step's name. */
export function authentikStepKey(step: string): string | null {
  const known = (AUTHENTIK_STEPS as readonly string[]).includes(step) || step === AUTHENTIK_STEP_BINDING
  return known ? `oidc.authentik.step.${step}` : null
}

/** The text key of a step's reason. */
export function authentikReasonKey(reason: string | null | undefined): string | null {
  return reason && (AUTHENTIK_REASONS as readonly string[]).includes(reason) ? `oidc.authentik.why.${reason}` : null
}

/**
 * The number of accounts the button asks about before it changes the issuer (`reason: issuer_change`, Bauplan 03), or
 * null when the run did not stop for that. The page then asks with `oidc.admin.issuerChangeConfirm` and, on yes, runs
 * the button again with `confirm_issuer_change: true`.
 */
export function authentikIssuerChange(result: {
  steps: ReadonlyArray<{ ok: boolean; reason?: string }>
  count?: number
}): number | null {
  const failed = result.steps.find((step) => !step.ok)
  return failed?.reason === 'issuer_change' ? (result.count ?? 0) : null
}

/**
 * What `GET <api>/oidc/authentik/address` answers, and `address` of a run refused with `public_url_needed`
 * (`authentik.address_view`, since 1.0.10).
 */
export interface AuthentikAddress {
  /** The app's public address, '' for none: then the card suggests the browser's own (`authentikProposal`). */
  public_url: string
  /** This request's address as the server sees it. */
  seen: string
  forwarded_proto: string
  forwarded_host: string
  /** A proxy named another scheme or host than the app took. */
  proxy_ignored: boolean
  /** What the button registers behind the public address, for example `/api/oidc/authentik/callback`. */
  callback_path: string
  /** The redirect address the sign-in sends today. */
  redirect_uri: string
  /** What the button registered at authentik last, '' for nothing. */
  registered_redirect_uri: string
  /** authentik still knows an older redirect address: the card shows `oidc.authentik.stale`. */
  stale: boolean
}

/**
 * The public address the authentik card suggests while the app has none: the address the browser uses plus the
 * app's base path, without a slash at the end. Call it as `authentikProposal(window.location.origin,
 * import.meta.env.BASE_URL)`; "Use it and set up" sends it as `public_url` with the button. A relative base (`./`,
 * `.`, as Vite writes it for `base: './'`) adds nothing, `./app/` adds `/app`.
 */
export function authentikProposal(origin: string, basePath = ''): string {
  let path = basePath.trim()
  if (path === '.' || path.startsWith('./')) path = path.slice(1)
  path = path.replace(/\/+$/, '')
  return origin.replace(/\/+$/, '') + (path && !path.startsWith('/') ? `/${path}` : path)
}

/** The redirect address the button registers behind a public address (shown under the suggestion). */
export function authentikRedirect(publicUrl: string, address: Pick<AuthentikAddress, 'callback_path'>): string {
  return publicUrl.replace(/\/+$/, '') + address.callback_path
}

const ORIGIN = /^([A-Za-z][A-Za-z0-9+.-]*):\/\/([^/?#]*)/

/**
 * How the browser's address differs from the one the server sees: `scheme` (http at the server, https in the
 * browser: a proxy ends TLS and the app does not take its word), `host`, or null. The same as the server's
 * `authentik.address_mismatch`.
 */
export function authentikAddressMismatch(proposal: string, seen: string): 'scheme' | 'host' | null {
  const browser = ORIGIN.exec(proposal.trim())
  const server = ORIGIN.exec(seen.trim())
  if (!browser || !server) return null
  const [, browserScheme = '', browserHost = ''] = browser
  const [, serverScheme = '', serverHost = ''] = server
  if (browserScheme.toLowerCase() !== serverScheme.toLowerCase()) return 'scheme'
  if (browserHost.toLowerCase() !== serverHost.toLowerCase()) return 'host'
  return null
}

/**
 * Whether the card shows `oidc.authentik.proxyWarning` (with `address` set to `address.seen`) under its suggestion:
 * the server sees another scheme or host than the browser uses, or a proxy said so and the app did not listen.
 */
export function authentikProxyWarning(
  proposal: string,
  address: Pick<AuthentikAddress, 'seen' | 'proxy_ignored'>,
): boolean {
  return address.proxy_ignored || authentikAddressMismatch(proposal, address.seen) !== null
}

/**
 * The redirect address authentik still knows when the public address changed after the button ran, else null: the
 * card shows `oidc.authentik.stale` with it until the button ran again. Takes the address view or the entry of the
 * provider list (`registered_redirect_uri`, `redirect_stale`).
 */
export function authentikStale(
  item: { registered_redirect_uri: string; stale?: boolean; redirect_stale?: boolean } | null | undefined,
): string | null {
  if (!item) return null
  return (item.stale ?? item.redirect_stale) && item.registered_redirect_uri ? item.registered_redirect_uri : null
}

/** A wording file (`oidc.de.json`, `oidc.en.json`) or a part of it. */
export interface OidcWording {
  [key: string]: string | OidcWording
}

function overlay(base: OidcWording, over: OidcWording): OidcWording {
  const merged: OidcWording = { ...base }
  for (const [key, value] of Object.entries(over)) {
    const below = merged[key]
    merged[key] = typeof value === 'object' && typeof below === 'object' ? overlay(below, value) : value
  }
  return merged
}

/**
 * The words of a wording file as the app merges them into its resources. Apps with one account (nexcrate, nexsift;
 * `AppConfig.single_account`) pass `singleAccount: true`: then the sentences under `oidc.single` take the place of
 * the keys of the same name (`oidc.admin.passwordHint`, `oidc.admin.addressHint`, `oidc.error.oidc_no_account`), so
 * the page asks for the same keys in every app. Apps without invitations (nexdeck, nexsift, nexcrate) pass
 * `invitations: false` (since 1.0.12, required: a call without it throws): then the sentences under `oidc.noInvitations` take the place of
 * `oidc.admin.addressHint`, `oidc.admin.autoCreateHint` and `oidc.error.oidc_no_account`; the sentences of one account
 * go on top of them. Neither `oidc.single` nor `oidc.noInvitations` is handed on. Counts use i18next's plural forms
 * (`_one`, `_other`): ask for the key without the suffix and pass `count`.
 */
export function oidcWording(
  file: OidcWording,
  options: { singleAccount: boolean; invitations: boolean },
): OidcWording {
  // A call from before 1.0.12 passes no `invitations`; reading that as "none" would put the sentences of an app without
  // invitations into an app that has them, unseen (vite and vitest do not check types).
  if (typeof options?.invitations !== 'boolean') {
    throw new Error('oidcWording: options.invitations must be true or false (required since 1.0.12)')
  }
  const root = file.oidc
  if (typeof root !== 'object') return { ...file }
  const { single, noInvitations, ...words } = root
  let chosen = words
  if (!options.invitations && typeof noInvitations === 'object') chosen = overlay(chosen, noInvitations)
  if (options.singleAccount && typeof single === 'object') chosen = overlay(chosen, single)
  return { ...file, oidc: chosen }
}

/**
 * What the app sets as i18next's `interpolation.defaultVariables` (since 1.0.12): `app`, the name of the app in the
 * texts, and `slug`, the slug the authentik button gives the app's application (in `oidc.admin.issuerHint`). The
 * button takes the server's `AppConfig.app_name`, which is the name in small letters (`Nexview` gives `nexview`);
 * pass `slug` only when the app's `app_name` is something else.
 */
export function oidcVariables(app: string, slug?: string): { app: string; slug: string } {
  return { app, slug: slug ?? slugFromLabel(app) }
}

const SPELLED_OUT: Record<string, string> = { ä: 'ae', ö: 'oe', ü: 'ue', ß: 'ss', Ä: 'Ae', Ö: 'Oe', Ü: 'Ue' }
const SLUG_MAX = 40

/**
 * The short name the form suggests for a name on the button, as the server does (`providers.slug_from_label`):
 * lower case, German letters written out, other accents dropped, everything else a dash, at most 40 characters.
 */
export function slugFromLabel(label: string): string {
  const spelled = label.replace(/[äöüßÄÖÜ]/g, (letter) => SPELLED_OUT[letter] ?? letter)
  // Only what ASCII has, as the server's encode('ascii', 'ignore'); a filter instead of a pattern with control
  // characters in it (eslint no-control-regex).
  const ascii = Array.from(spelled.normalize('NFKD'))
    .filter((char) => char.charCodeAt(0) < 128)
    .join('')
  const slug = ascii
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '')
  return slug.slice(0, SLUG_MAX).replace(/-+$/, '')
}
