/** Legt den Betreiber an und merkt sich seine Sitzung (das Cookie `nexbeat_refresh`) fuer die Tests. */
import { request } from '@playwright/test'

export default async function globalSetup(): Promise<void> {
  const context = await request.newContext({ baseURL: 'http://127.0.0.1:8036' })
  const made = await context.post('/api/setup/admin', {
    data: { username: 'operator', email: 'operator@example.com', password: process.env.NEXBEAT_E2E_PASSWORD, language: 'de' },
  })
  if (!made.ok()) throw new Error(`setup failed: ${made.status()} ${await made.text()}`)
  await context.storageState({ path: process.env.NEXBEAT_E2E_STATE })
  await context.dispose()
}
