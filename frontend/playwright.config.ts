/**
 * Ende-zu-Ende fuer die Anmeldung ueber Anbieter, kopflos. Die gebaute
 * Oberflaeche kommt vom echten Server wie im Container (`app.main:asgi`), mit eigenem Datenordner und eigenem Port,
 * daneben ein nachgebauter Anbieter (`e2e/fake-oidc.mjs`). Nie ein echter Anbieter, nie das Netz, nie `data/`.
 *
 * Playwright steht nicht in package.json (CI braucht es nicht). Lokal:
 *   npm install --no-save @playwright/test@1.63.0
 *   npm run build
 *   npx playwright test
 */
import { randomBytes } from 'node:crypto'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'

import { defineConfig } from '@playwright/test'

export const PORT = 8036
export const PROVIDER_PORT = 8037

function dataDir(): string {
  if (process.env.NEXBEAT_E2E_DATA) return process.env.NEXBEAT_E2E_DATA
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'nexbeat-e2e-'))
  process.env.NEXBEAT_E2E_DATA = dir
  // Das Passwort des Betreibers, je Lauf neu; die Tests lesen es aus der Umgebung.
  process.env.NEXBEAT_E2E_PASSWORD = randomBytes(12).toString('base64url')
  return dir
}

const DATA_DIR = dataDir()
const SIGNED_IN = path.join(DATA_DIR, 'e2e-operator.json')
process.env.NEXBEAT_E2E_STATE = SIGNED_IN
const python = path.join('.venv', process.platform === 'win32' ? 'Scripts/python.exe' : 'bin/python')

export default defineConfig({
  testDir: './e2e',
  globalSetup: './e2e/global-setup.ts',
  fullyParallel: false,
  workers: 1,
  retries: 0,
  reporter: 'list',
  use: { baseURL: `http://127.0.0.1:${PORT}`, headless: true, locale: 'de-DE', storageState: SIGNED_IN },
  webServer: [
    {
      command: `${python} -m uvicorn app.main:asgi --no-proxy-headers --host 127.0.0.1 --port ${PORT}`,
      cwd: path.join('..', 'backend'),
      url: `http://127.0.0.1:${PORT}/api/health`,
      reuseExistingServer: false,
      timeout: 120_000,
      env: {
        NEXBEAT_DATA_DIR: path.join(DATA_DIR, 'data'),
        NEXBEAT_FRONTEND_DIST: path.resolve('dist'),
        NEXBEAT_SECRET_KEY: randomBytes(24).toString('base64url'),
        NEXBEAT_DISABLE_BACKGROUND: 'true',
      },
    },
    {
      command: 'node e2e/fake-oidc.mjs',
      url: `http://localhost:${PROVIDER_PORT}/health`,
      reuseExistingServer: false,
      timeout: 20_000,
      env: { FAKE_OIDC_PORT: String(PROVIDER_PORT) },
    },
  ],
})
