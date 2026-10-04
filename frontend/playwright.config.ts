import { defineConfig, devices } from '@playwright/test'
import { AUTH_STATE } from './e2e/auth-state'

/**
 * e2e идут против стека в Docker (`make up`), по умолчанию http://localhost:8080.
 * Свой адрес — E2E_BASE_URL (например, vite на :5176 + mock-backend на :8000 с MOCK_DELAY_SCALE=0.2).
 * Проект screenshots снимает ключевые экраны для команды: `make screenshots` → reports/screenshots.
 *
 * Если на стенде включены аккаунты, `e2e/global-setup.ts` регистрирует тестового пользователя и
 * сохраняет вход; сценарии идут под ним. Экран входа проверяет `auth.spec.ts` без этого состояния.
 *
 * Микрофон — поддельный: Chromium отдаёт тестовый сигнал без запроса разрешения, поэтому
 * сценарий записи голоса проходит без человека.
 */
const fakeMedia = {
  launchOptions: {
    args: ['--use-fake-device-for-media-stream', '--use-fake-ui-for-media-stream'],
  },
  permissions: ['microphone'],
}

export default defineConfig({
  testDir: './e2e',
  globalSetup: './e2e/global-setup.ts',
  fullyParallel: true,
  // E2E-сценарии используют общий демо-проект. Последовательный режим в CI
  // исключает взаимное изменение вопросов и прогонов между тестами.
  workers: process.env.CI ? 1 : undefined,
  forbidOnly: !!process.env.CI,
  retries: 0,
  timeout: 60_000,
  expect: { timeout: 10_000 },
  reporter: [['list'], ['html', { open: 'never' }]],
  use: {
    baseURL: process.env.E2E_BASE_URL ?? 'http://localhost:8080',
    locale: 'ru-RU',
    trace: 'retain-on-failure',
    viewport: { width: 1440, height: 900 },
    storageState: AUTH_STATE,
  },
  projects: [
    {
      name: 'e2e',
      testIgnore: /screenshots\.spec\.ts/,
      use: { ...devices['Desktop Chrome'], viewport: { width: 1440, height: 900 }, ...fakeMedia },
    },
    {
      name: 'screenshots',
      testMatch: /screenshots\.spec\.ts/,
      timeout: 180_000,
      use: {
        ...devices['Desktop Chrome'],
        viewport: { width: 1600, height: 1000 },
        deviceScaleFactor: 2,
        ...fakeMedia,
      },
    },
  ],
})
