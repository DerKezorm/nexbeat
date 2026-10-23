/**
 * Every text of the oidc module is in the app, in German and English, through the app's own i18n. Copied once by
 * the module's `tools/sync.py` to `frontend/src/nexoidc.wording.test.ts`; then the
 * app's file. Fill in the places marked APP.
 *
 * The module's own tests already check the wording files word for word; this test checks that the
 * app really loads them (merged into its resources, `{{app}}` and `{{slug}}` filled in) and that nothing in the app
 * overrides them.
 */
import { beforeAll, describe, expect, it } from 'vitest'

import { oidcVariables, oidcWording, type OidcWording } from './vendor/nexoidc/oidc'
import de from './vendor/nexoidc/oidc.de.json'
import en from './vendor/nexoidc/oidc.en.json'
// nexbeat: the i18n instance after its set-up (i18n/index.ts merges the module's files into the resources).
import i18n, { changeLanguage, startI18n } from './i18n'

// APP: the name of the app as it appears in the texts.
const APP_NAME = 'nexbeat'
// APP: the slug the authentik button gives the app (the server's app_name), only if it is not the name in small
// letters; the app sets the same through oidcVariables in its i18n (since 1.0.12).
const APP_SLUG = oidcVariables(APP_NAME).slug
// APP: true for the apps with one account (nexcrate, nexsift); the app merges the files through oidcWording.
const SINGLE_ACCOUNT = false
// APP: false for the apps without invitations (nexdeck, nexsift, nexcrate; since 1.0.12).
const INVITATIONS = true
const WORDING = { singleAccount: SINGLE_ACCOUNT, invitations: INVITATIONS }

type Tree = OidcWording

function leaves(tree: Tree, prefix = ''): [string, string][] {
  return Object.entries(tree).flatMap(([name, value]) => {
    const key = prefix ? `${prefix}.${name}` : name
    return typeof value === 'string' ? [[key, value] as [string, string]] : leaves(value, key)
  })
}

// Every placeholder of the texts but `{{app}}` and `{{slug}}`, which the app's i18n fills in itself (`address` since 1.0.10, in the template since 1.0.11).
const values = { name: 'N', count: 2, only: 1, status: 403, address: 'https://app.example.com' }

beforeAll(async () => {
  await startI18n('de')
})

describe('the oidc texts', () => {
  for (const [language, tree] of [['de', de], ['en', en]] as const) {
    it(`are all in the app in ${language}, word for word, with the app's name`, async () => {
      // nexbeat loads a language when it is switched to (no fallback language).
      await changeLanguage(language)
      for (const [key, text] of leaves(oidcWording(tree, WORDING))) {
        // Plural forms are asked for without their suffix, with a count that picks them (since 1.0.9).
        const plural = /_(one|other)$/.exec(key)
        const given = plural ? { ...values, count: plural[1] === 'one' ? 1 : 2 } : values
        const asked = plural ? key.slice(0, plural.index) : key
        const expected = text.replace(/\{\{(\w+)\}\}/g, (_, name: string) =>
          name === 'app' ? APP_NAME : name === 'slug' ? APP_SLUG : String(given[name as keyof typeof given]),
        )
        expect(i18n.t(asked, given), key).toBe(expected)
      }
    })
  }
})
