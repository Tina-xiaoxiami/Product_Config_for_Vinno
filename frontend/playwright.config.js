import { defineConfig } from '@playwright/test'
import { mkdtempSync } from 'node:fs'
import { join } from 'node:path'

const fixtureDirectory = mkdtempSync('/tmp/probe-e2e-')

export default defineConfig({
  testDir: './e2e',
  fullyParallel: false,
  workers: 1,
  retries: 0,
  timeout: 60000,
  use: { baseURL: 'http://127.0.0.1:3006', headless: true, trace: 'retain-on-failure', screenshot: 'only-on-failure' },
  reporter: [['list'], ['html', { open: 'never' }]],
  webServer: [
    { command: 'python -m uvicorn probe_e2e_app:app --app-dir ../tests --host 127.0.0.1 --port 8086',
      url: 'http://127.0.0.1:8086/api/probes/workspaces', reuseExistingServer: false,
      env: { PROBE_E2E: '1', DATABASE_URL: `sqlite+aiosqlite:///${join(fixtureDirectory, 'probe-e2e.db')}`, WHITEPAPER_SUBSERIES_FILE: join(fixtureDirectory, 'probe-e2e-subseries.json') } },
    { command: 'npm run dev', url: 'http://127.0.0.1:3006', reuseExistingServer: false },
  ],
})
