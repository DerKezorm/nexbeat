/**
 * Pflichttests 33 und 34 der gemeinsamen Anmeldung (einmal aus bauplaene/oidc kopiert, dann nexbeats Datei).
 *
 * Der Anbieter ist der nachgebaute aus `e2e/fake-oidc.mjs` (http://localhost:8037, eine andere Site als nexbeat auf
 * 127.0.0.1). Nie ein echter Anbieter, nie das Netz. Die Seite ist der Betreiber `operator` aus `global-setup.ts`.
 */
import { expect, test, type APIRequestContext, type Page } from '@playwright/test'

const PROVIDER = 'http://localhost:8037'
const PASSWORD = process.env.NEXBEAT_E2E_PASSWORD ?? ''

type Entry = { id: number; slug: string }

/** nexbeats Schnittstelle will den Zugangs-Token im Kopf; das Cookie der Sitzung tauscht ihn ein. */
async function bearer(request: APIRequestContext): Promise<Record<string, string>> {
  const refreshed = await request.post('/api/auth/refresh')
  expect(refreshed.ok(), await refreshed.text()).toBe(true)
  return { Authorization: `Bearer ${(await refreshed.json()).access_token}` }
}

async function removeEntry(page: Page, slug: string): Promise<void> {
  const headers = await bearer(page.request)
  const entries = (await (await page.request.get('/api/oidc/admin/providers', { headers })).json()) as Entry[]
  for (const entry of entries) {
    if (entry.slug === slug) await page.request.delete(`/api/oidc/admin/providers/${entry.id}`, { headers })
  }
}

function collectProblems(page: Page): string[] {
  const problems: string[] = []
  page.on('console', (message) => {
    // Vor der Anmeldung fragt die Seite /api/auth/refresh und bekommt 401 ("niemand angemeldet"); 422 ist der gewollt
    // abgewiesene Aussteller im Formular. Der Browser schreibt beides als Fehler, die Seite zeigt es in Worten.
    if (message.type() === 'error' && !/status of (40[134]|422)/.test(message.text())) problems.push(message.text())
  })
  page.on('pageerror', (error) => problems.push(error.message))
  return problems
}

async function nextPerson(person: object): Promise<void> {
  await fetch(`${PROVIDER}/next`, { method: 'POST', body: JSON.stringify(person) })
}

test('33: sign-in through the provider button ends in a session', async ({ page, browser }) => {
  const problems = collectProblems(page)
  await removeEntry(page, 'standin')
  const made = await page.request.post('/api/oidc/admin/providers', {
    data: { label: 'Stand-in', slug: 'standin', issuer: PROVIDER, client_id: 'e2e-client', client_secret: `e2e-${Date.now()}` },
    headers: await bearer(page.request),
  })
  expect(made.ok(), await made.text()).toBe(true)
  await nextPerson({ sub: 'operator-33', preferred_username: 'someone-else', email: 'operator@example.com' })

  // Verknuepfen unter Profil: das Passwort noch einmal, dann zum Anbieter und zurueck.
  await page.goto('/profil')
  const row = page.getByTestId('provider-links').getByRole('listitem').filter({ hasText: 'Stand-in' })
  await expect(row).toContainText('Nicht verknüpft')
  await row.getByRole('button', { name: 'Verknüpfen' }).click()
  const dialog = page.getByRole('dialog')
  await dialog.getByLabel('Aktuelles Passwort').fill(PASSWORD)
  await dialog.getByRole('button', { name: 'Verknüpfen' }).click()
  // Der Name des Anbieters, nicht der Kurzname aus der Adresse.
  await expect(page.getByText('Dein Konto ist jetzt mit Stand-in verknüpft.')).toBeVisible()
  await expect(page.getByTestId('provider-links').getByRole('listitem').filter({ hasText: 'Stand-in' })).toContainText('Verknüpft')
  expect(problems).toEqual([])

  // Ein Browser ohne Sitzung: der Knopf auf der Anmeldeseite, und hinein.
  const fresh = await browser.newContext({ storageState: { cookies: [], origins: [] } })
  const visitor = await fresh.newPage()
  const visitorProblems = collectProblems(visitor)
  await visitor.goto('/login')
  await visitor.getByRole('button', { name: 'Mit Stand-in anmelden' }).click()
  await visitor.waitForURL((url) => url.port === '8036' && !url.pathname.startsWith('/api/'))
  await expect(visitor).not.toHaveURL(/error=/)
  const me = await visitor.request.get('/api/auth/me', { headers: await bearer(visitor.request) })
  expect((await me.json()).username).toBe('operator')
  expect(visitorProblems).toEqual([])
  await fresh.close()

  // Eine fremde Person beim Anbieter, mit derselben Adresse und bestaetigt: kein Konto, die Seite sagt es in Worten.
  await nextPerson({ sub: 'stranger-33', email: 'operator@example.com', email_verified: true })
  const strange = await browser.newContext({ storageState: { cookies: [], origins: [] } })
  const stranger = await strange.newPage()
  await stranger.goto('/login')
  await stranger.getByRole('button', { name: 'Mit Stand-in anmelden' }).click()
  await expect(stranger.getByText('Für dich gibt es hier kein Konto.', { exact: false })).toBeVisible()
  expect((await stranger.request.post('/api/auth/refresh')).status()).toBe(401)
  await strange.close()

  // Wieder loesen: das Passwort bleibt der Weg.
  await page.goto('/profil')
  await page.getByTestId('provider-links').getByRole('listitem').filter({ hasText: 'Stand-in' }).getByRole('button', { name: 'Lösen' }).click()
  await expect(page.getByTestId('provider-links').getByRole('listitem').filter({ hasText: 'Stand-in' })).toContainText('Nicht verknüpft')
  await removeEntry(page, 'standin')
})

test('34: add, edit and remove a provider; the authentik card lists its steps', async ({ page }) => {
  const problems = collectProblems(page)
  await removeEntry(page, 'stand-in')
  await page.goto('/admin/einstellungen?reiter=anmeldung')
  await expect(page.getByRole('heading', { name: 'Anmeldung', exact: true })).toBeVisible()
  await expect(page.getByRole('heading', { name: 'Anmeldeanbieter' })).toBeVisible()
  await expect(page.getByRole('heading', { name: 'authentik in einem Schritt' })).toBeVisible()
  await page.getByRole('button', { name: 'Anbieter hinzufügen' }).click()
  const form = page.getByTestId('provider-form')
  await form.getByLabel('Name auf dem Knopf').fill('Stand-in')
  // Der Kurzname folgt dem Namen, die Rueckleitadresse dem Kurznamen.
  await expect(form.getByLabel('Kurzname')).toHaveValue('stand-in')
  await expect(form.getByTestId('provider-redirect')).toHaveText(/\/api\/oidc\/stand-in\/callback$/)
  // Ein Aussteller, der nicht als einer antwortet, wird am Feld abgewiesen, und nichts ist gespeichert.
  await form.getByLabel('Aussteller (Issuer)').fill(`${PROVIDER}/nothing-here`)
  await form.getByLabel('Client-ID').fill('e2e-client')
  await form.getByLabel('Client-Geheimnis').fill(`e2e-${Date.now()}`)
  await form.getByRole('button', { name: 'Speichern' }).click()
  await expect(form.getByRole('alert')).toBeVisible()
  await form.getByLabel('Aussteller (Issuer)').fill(PROVIDER)
  await form.getByRole('button', { name: 'Speichern' }).click()
  const list = page.getByTestId('provider-list')
  const row = list.getByRole('listitem').filter({ hasText: 'Stand-in' })
  await expect(row).toContainText(PROVIDER)
  await expect(row).toContainText('aktiv')
  await row.getByRole('button', { name: 'Bearbeiten' }).click()
  await expect(form.getByText('stand-in', { exact: true })).toBeVisible()
  await form.getByLabel('Name auf dem Knopf').fill('Stand-in 2')
  await form.getByRole('button', { name: 'Speichern' }).click()
  const renamed = list.getByRole('listitem').filter({ hasText: 'Stand-in 2' })
  await expect(renamed).toBeVisible()
  // Die Anmeldeseite hat jetzt ihren Knopf.
  const listed = await (await page.request.get('/api/oidc/providers')).json()
  expect(listed).toContainEqual({ slug: 'stand-in', label: 'Stand-in 2' })
  await renamed.getByRole('button', { name: 'Entfernen' }).click()
  const question = page.getByRole('dialog')
  await expect(question).toContainText('Konten verlieren die Verknüpfung')
  await question.getByRole('button', { name: 'Entfernen' }).click()
  await expect(page.getByText('Stand-in 2')).toHaveCount(0)
  // Die authentik-Karte: unter einer Adresse, an der niemand antwortet, scheitert der erste Schritt, in Worten.
  await page.getByLabel('Adresse von authentik').fill('http://127.0.0.1:9')
  await page.getByLabel('API-Token').fill(`e2e-${Date.now()}`)
  // Ohne oeffentliche Adresse (eine frische App) heisst der Knopf "Uebernehmen und einrichten" (1.0.10).
  await page.getByRole('button', { name: /^(Einrichten|Übernehmen und einrichten)$/ }).click()
  const steps = page.getByTestId('authentik-steps')
  await expect(steps).toContainText('Verbindung zu authentik')
  await expect(steps).toContainText('authentik ist unter dieser Adresse nicht erreichbar.')
  expect(problems).toEqual([])
})
