import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { type APIRequestContext, expect, type Locator, type Page } from '@playwright/test'

/** Демо-проект из сида mock-бэкенда (`DEMO_PROJECT_ID` в backend/app/infra/seed.py). */
export const DEMO_PROJECT_ID = '55323c54-3524-5676-abfd-01f834ddad13'
export const DEMO_PROJECT_TITLE = 'Технологическое присоединение к электросетям'

/** Входные материалы примера tp861 из корня репозитория. */
export const FINANCES_MD = fileURLToPath(
  new URL('../../examples/tp861/input/project-finances.md', import.meta.url),
)

export function readExample(path: string): string {
  return readFileSync(path, 'utf8')
}

/**
 * Изменяющий запрос к API от имени вошедшего пользователя. Когда на стенде включены аккаунты,
 * сервер требует CSRF-токен из `/auth/csrf` (cookie уже в состоянии входа) — берём свежий.
 */
export async function apiPost(request: APIRequestContext, url: string, data: unknown) {
  const { csrf_token: csrf } = await (await request.get('/api/v1/auth/csrf')).json()
  return request.post(url, { data, headers: { 'X-CSRF-Token': csrf } })
}

/** Свежий проект из примера: сценарии не зависят от того, что делали с демо-проектом раньше. */
export async function createExampleProject(
  request: APIRequestContext,
  exampleId = 'tp861',
): Promise<string> {
  const response = await apiPost(request, '/api/v1/projects/from-example', {
    example_id: exampleId,
  })
  expect(response.ok()).toBeTruthy()
  return (await response.json()).id as string
}

/** Создать проект из примера и прогнать анализ/сборку через API (для снимков и проверок). */
export async function runViaApi(
  request: APIRequestContext,
  projectId: string,
  mode: 'analyze' | 'build',
) {
  const started = await apiPost(request, `/api/v1/projects/${projectId}/runs`, { mode })
  expect(started.ok()).toBeTruthy()
  const run = await started.json()
  await expect
    .poll(
      async () => (await (await request.get(`/api/v1/runs/${run.id}`)).json()).status as string,
      { timeout: 30_000 },
    )
    .toBe('succeeded')
}

export function questionCard(page: Page, code: string): Locator {
  return page.locator(`[data-question="${code}"]`)
}

/** Запустить прогон кнопкой и дождаться его конца по карточке хода (role=status, SSE). */
export async function startRun(page: Page, mode: 'analyze' | 'build') {
  const button =
    mode === 'analyze'
      ? page.getByRole('button', { name: 'Анализ', exact: true })
      : page.getByRole('button', { name: 'Построить схему' }).first()
  await button.click()
  const card = page.getByRole('status', { name: /Ход прогона/ })
  // Сначала появляются этапы нового прогона, затем итог.
  await expect(card.getByRole('list', { name: 'Этапы прогона' })).toBeVisible()
  await expect(card).toContainText(mode === 'analyze' ? 'Анализ завершён' : 'Схема построена', {
    timeout: 30_000,
  })
  return card
}

/** Перетащить элемент схемы мышью — настоящая правка в bpmn-js. */
export async function dragElement(page: Page, elementId: string, dx: number, dy: number) {
  const box = await page.locator(`[data-element-id="${elementId}"]`).first().boundingBox()
  if (!box) throw new Error(`Элемент ${elementId} не найден на схеме`)
  const x = box.x + box.width / 2
  const y = box.y + box.height / 2
  await page.mouse.move(x, y)
  await page.mouse.down()
  await page.mouse.move(x + dx, y + dy, { steps: 10 })
  await page.mouse.up()
}
