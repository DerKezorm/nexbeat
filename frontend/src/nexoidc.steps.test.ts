/**
 * Every step the authentik button reports and every reason it gives has a sentence in
 * both languages, and no language has a step or reason the server never sends. The server's lists are the module's
 * (`authentik.STEP_KEYS`, `authentik.REASONS`), mirrored in `oidc.ts` and checked against each other in the module's own tests.
 */
import { beforeAll, describe, expect, it } from 'vitest'

import i18n, { changeLanguage, startI18n } from './i18n'
import {
  AUTHENTIK_REASONS,
  AUTHENTIK_STEP_BINDING,
  AUTHENTIK_STEPS,
  authentikReasonKey,
  authentikStepKey,
} from './vendor/nexoidc/oidc'
import de from './vendor/nexoidc/oidc.de.json'
import en from './vendor/nexoidc/oidc.en.json'

beforeAll(async () => {
  await startI18n('de')
})

const plain = (key: string) => key.replace(/_(one|other)$/, '')

describe('the steps and reasons of the authentik button', () => {
  for (const [language, tree] of [['de', de], ['en', en]] as const) {
    it(`have a sentence each in ${language}`, async () => {
      await changeLanguage(language)
      for (const step of AUTHENTIK_STEPS) {
        const key = authentikStepKey(step)
        expect(key && i18n.exists(key), step).toBe(true)
      }
      for (const reason of AUTHENTIK_REASONS) {
        const key = authentikReasonKey(reason)
        expect(key && i18n.t(key, { count: 2, status: 403 }) !== key, reason).toBe(true)
      }
    })

    it(`name nothing in ${language} that the server never sends`, () => {
      const steps = Object.keys(tree.oidc.authentik.step)
      expect(steps.sort()).toEqual([...AUTHENTIK_STEPS, AUTHENTIK_STEP_BINDING].sort())
      const reasons = [...new Set(Object.keys(tree.oidc.authentik.why).map(plain))]
      expect(reasons.sort()).toEqual([...AUTHENTIK_REASONS].sort())
    })
  }
})
