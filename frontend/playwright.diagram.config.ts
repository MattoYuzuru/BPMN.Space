import { defineConfig } from '@playwright/test'

/** Настоящий canvas и dev-API редактора, без общего проекта и backend. */
export default defineConfig({
  testDir: './e2e',
  testMatch: /diagram-playback\.spec\.ts/,
  fullyParallel: true,
  workers: 2,
  timeout: 45_000,
  expect: { timeout: 12_000 },
  use: {
    baseURL: 'http://127.0.0.1:5189',
    viewport: { width: 1440, height: 900 },
    trace: 'retain-on-failure',
  },
  webServer: {
    command: 'npm run dev -- --host 127.0.0.1 --port 5189 --strictPort',
    url: 'http://127.0.0.1:5189/dev/diagram',
    reuseExistingServer: false,
    timeout: 30_000,
  },
})
