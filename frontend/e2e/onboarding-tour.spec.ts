import { randomUUID } from 'node:crypto'
import {
  type APIRequestContext,
  type Browser,
  type BrowserContext,
  expect,
  type Locator,
  type Page,
  test,
} from '@playwright/test'

/**
 * Обучение: приветствие и тур из 11 шагов. Каждый сценарий регистрирует своего пользователя
 * (у общего тестового пользователя тур отклонён в global-setup). Ветвления прогона проверяются
 * маркерами mock-модели в тексте источника. Нужны аккаунты и включённый онбординг на стенде.
 */
test.beforeEach(async ({ request }) => {
  const session = await (await request.get('/api/v1/auth/session')).json()
  test.skip(!session.auth_enabled, 'Обучение работает только с аккаунтами')
  const state = await (await request.get('/api/v1/me/onboarding')).json()
  test.skip(!state.enabled, 'Онбординг на стенде выключен')
})

// Регистраций на стенде не больше 20 в минуту: сценарии, которым не нужно «ещё не предлагали тур»,
// делят одного пользователя и идут по очереди (тур для каждого сценария заводится заново).
test.describe.configure({ mode: 'serial' })

const SIGNED_OUT = { cookies: [], origins: [] }
const PROJECT_TITLE = 'Мой первый процесс'

interface Player {
  context: BrowserContext
  page: Page
  request: APIRequestContext
  email: string
  password: string
}

/**
 * Изменяющий запрос от имени пользователя: сервер ждёт CSRF-токен из `/auth/csrf`. Страница в том
 * же контексте тоже берёт токен и меняет cookie, поэтому при отказе (403) берём свежий и повторяем.
 */
async function send(
  request: APIRequestContext,
  method: 'post' | 'patch',
  url: string,
  data?: unknown,
) {
  let response = await request[method](url, { data, headers: await csrfHeaders(request) })
  for (let attempt = 0; attempt < 3 && response.status() === 403; attempt += 1) {
    response = await request[method](url, { data, headers: await csrfHeaders(request) })
  }
  expect(response.ok(), `${method} ${url}: ${response.status()}`).toBeTruthy()
  return response.status() === 204 ? null : response.json()
}

async function csrfHeaders(request: APIRequestContext) {
  const { csrf_token: csrf } = await (await request.get('/api/v1/auth/csrf')).json()
  return { 'X-CSRF-Token': csrf as string }
}

/** Новый пользователь, уже вошедший (через API): тур ему ещё не предлагали. */
async function newPlayer(browser: Browser, baseURL: string | undefined): Promise<Player> {
  const context = await browser.newContext({
    baseURL,
    locale: 'ru-RU',
    viewport: { width: 1440, height: 900 },
    storageState: SIGNED_OUT,
    permissions: ['microphone'],
  })
  const email = `e2e-tour-${randomUUID()}@example.com`
  const password = `pw-${randomUUID()}`
  const request = context.request
  // Лимит регистраций на адрес — 20 в минуту: при 429 ждём Retry-After и пробуем ещё раз.
  const authorize = async (
    url: string,
    options: { data?: unknown; form?: Record<string, string> },
  ) => {
    let response = await request.post(url, { ...options, headers: await csrfHeaders(request) })
    if (response.status() === 429) {
      const wait = Number(response.headers()['retry-after'] ?? 5)
      await new Promise((resolve) => setTimeout(resolve, Math.min(wait, 60) * 1000))
      response = await request.post(url, { ...options, headers: await csrfHeaders(request) })
    }
    return response
  }
  expect(
    (await authorize('/api/v1/auth/register', { data: { email, password } })).ok(),
  ).toBeTruthy()
  const login = await authorize('/api/v1/auth/session/login', {
    form: { username: email, password },
  })
  expect(login.ok()).toBeTruthy()
  return { context, page: await context.newPage(), request, email, password }
}

let shared: Promise<Player> | undefined

/** Общий пользователь для сценариев с готовым состоянием тура; у каждого сценария — своя вкладка. */
async function sharedPlayer(browser: Browser, baseURL: string | undefined): Promise<Player> {
  shared ??= newPlayer(browser, baseURL)
  const player = await shared
  return { ...player, page: await player.context.newPage() }
}

test.afterAll(async () => {
  await (await shared)?.context.close()
})

/** Карточка тура по заголовку шага. */
function coach(page: Page, title: string): Locator {
  return page.getByRole('dialog', { name: title })
}

async function tourState(request: APIRequestContext) {
  return (await request.get('/api/v1/me/onboarding')).json()
}

/** Учебный проект с одним текстовым источником (маркер mock-модели — в тексте) и тур на шаге. */
async function seedTour(
  player: Player,
  step: string,
  { text, markers = '' }: { text?: boolean | string; markers?: string } = {},
) {
  const { request } = player
  const project = await send(request, 'post', '/api/v1/projects', { title: PROJECT_TITLE })
  if (text) {
    const suggestion = (await tourState(request)).tour_text_suggestion as string
    await send(request, 'post', `/api/v1/projects/${project.id}/sources/text`, {
      kind: 'text',
      title: 'Описание процесса',
      content: `${typeof text === 'string' ? text : suggestion}\n${markers}`,
    })
  }
  await send(request, 'post', '/api/v1/me/onboarding/tour/restart')
  await send(request, 'patch', '/api/v1/me/onboarding/tour', {
    step,
    project_id: project.id,
  })
  return project.id as string
}

test('приветствие и весь тур от создания проекта до чек-листа', async ({ browser, baseURL }) => {
  test.setTimeout(240_000)
  const { page, request, context } = await newPlayer(browser, baseURL)
  // Регистрация через интерфейс не нужна: вход уже есть, как после регистрации.

  await test.step('приветствие появляется на экране проектов', async () => {
    await page.goto('/projects')
    const welcome = page.getByRole('dialog', { name: 'Добро пожаловать в Архитектор' })
    await expect(welcome).toBeVisible()
    await expect(welcome.getByRole('button', { name: 'Закрыть' })).toHaveCount(0)
    await welcome.getByRole('button', { name: 'Пройти обучение' }).click()
    await expect(welcome).toBeHidden()
    expect((await tourState(request)).tour).toMatchObject({
      status: 'active',
      step: 'project.create',
    })
  })

  await test.step('шаг 1: проект создаётся по подсвеченной кнопке, название заполнено', async () => {
    await expect(coach(page, 'Создайте проект')).toBeVisible()
    await expect(coach(page, 'Создайте проект')).toContainText('Шаг 1 из 11')
    await page.getByRole('button', { name: 'Новый проект' }).first().click()
    const dialog = page.getByRole('dialog', { name: 'Новый проект' })
    await expect(dialog.getByRole('textbox', { name: 'Название' })).toHaveValue(PROJECT_TITLE)
    await expect(dialog.getByRole('radio', { name: 'Из примера' })).toHaveCount(0)
    await expect(dialog.getByText('Описание процесса')).toHaveCount(0)
    await expect(dialog.getByText('Документы')).toHaveCount(0)
    await dialog.getByRole('button', { name: 'Создать проект' }).click()
    await expect(page).toHaveURL(/\/projects\/[\w-]+$/)
  })

  await test.step('шаг 2: пример из меню «Примеры»', async () => {
    const card = coach(page, 'Добавьте источник')
    await expect(card).toBeVisible()
    await card.getByRole('button', { name: 'Далее' }).click()
    await page.getByRole('button', { name: 'Добавить источник' }).click()
    const menu = page.getByRole('menu')
    await expect(menu.getByText('Примеры')).toBeVisible()
    await menu.getByRole('menuitem', { name: /Записка со встречи/ }).click()
    await expect(page.getByRole('region', { name: 'Источники' })).toContainText(
      'Записка со встречи',
    )
  })

  await test.step('шаг 3: текст по подсказке-автодополнению', async () => {
    await expect(coach(page, 'Опишите процесс')).toBeVisible()
    await page.getByRole('button', { name: 'Добавить источник' }).click()
    await page.getByRole('menuitem', { name: 'Текст', exact: true }).click()
    const dialog = page.getByRole('dialog', { name: 'Текстовый источник' })
    const field = dialog.getByRole('textbox', { name: 'Текст' })
    await expect(field).toBeFocused()
    await expect(dialog.getByRole('button', { name: 'Напишу сам' })).toBeVisible()
    await dialog.getByRole('button', { name: 'Вставить' }).click()
    // Текст впечатывается в поле, а не появляется разом.
    await expect.poll(async () => (await field.inputValue()).length).toBeGreaterThan(20)
    await expect
      .poll(async () => (await field.inputValue()).length, { timeout: 15_000 })
      .toBeGreaterThan(300)
    await expect(dialog.getByRole('textbox', { name: 'Название' })).toHaveValue('Описание процесса')
    await dialog.getByRole('button', { name: 'Добавить источник' }).click()
    await expect(dialog).toBeHidden()
  })

  await test.step('шаг 4: голос можно пропустить', async () => {
    const card = coach(page, 'Надиктуйте процесс')
    await expect(card).toBeVisible()
    await card.getByRole('button', { name: 'Пропустить шаг' }).click()
  })

  await test.step('шаг 5: ждём разбор документа, затем «Построить схему»', async () => {
    const card = coach(page, 'Постройте схему')
    await expect(card).toBeVisible()
    await expect(card).toContainText('Модель прочитает источники', { timeout: 30_000 })
    await page.getByRole('banner').getByRole('button', { name: 'Построить схему' }).click()
  })

  await test.step('шаг 6: ход прогона', async () => {
    await expect(coach(page, 'Модель работает')).toBeVisible()
  })

  await test.step('шаг 7: ответ на первый открытый вопрос', async () => {
    const card = coach(page, 'Ответьте на вопрос')
    await expect(card).toBeVisible({ timeout: 90_000 })
    await expect(card).toContainText('Шаг 7 из 11')
    const first = page.locator('[data-question-id]').first()
    await first.getByRole('button', { name: 'Ответить', exact: true }).click()
    await first
      .getByRole('textbox')
      .fill('Акт готовит сетевая организация в течение трёх рабочих дней.')
    await first.getByRole('button', { name: 'Отправить ответ' }).click()
  })

  await test.step('шаг 8: игнорировать другой вопрос', async () => {
    const card = coach(page, 'Или примите допущение')
    await expect(card).toBeVisible()
    const answered = page.locator('[data-question-id]', { hasText: 'Ваш ответ' })
    const open = page
      .locator('[data-question-id]')
      .filter({ has: page.getByRole('button', { name: 'Игнорировать' }) })
    await expect(answered).toHaveCount(1)
    await open.first().getByRole('button', { name: 'Игнорировать' }).click()
  })

  await test.step('шаг 9: рассказ о схеме, три страницы', async () => {
    const card = coach(page, 'Посмотрите схему')
    await expect(card).toBeVisible()
    await expect(card).toContainText('обычный редактор BPMN')
    await card.getByRole('button', { name: 'Далее' }).click()
    await expect(card).toContainText('Таймлайн процесса')
    await card.getByRole('button', { name: 'Далее' }).click()
    await expect(card).toContainText('.bpmn, .svg или .png')
    await card.getByRole('button', { name: 'Далее' }).click()
  })

  await test.step('шаг 10: ссылка доступа', async () => {
    const card = coach(page, 'Поделитесь схемой')
    await expect(card).toBeVisible()
    await page.getByRole('button', { name: 'Поделиться' }).click()
    const dialog = page.getByRole('dialog', { name: 'Поделиться проектом' })
    await dialog.getByRole('button', { name: 'Создать ссылку' }).click()
    await expect(dialog.getByRole('textbox', { name: 'Ссылка' })).toBeVisible()
    await expect(coach(page, 'Поделитесь схемой')).toContainText('Ссылка создана')
    await coach(page, 'Поделитесь схемой').getByRole('button', { name: 'Далее' }).click()
  })

  await test.step('шаг 11: финал, сервер знает о прохождении', async () => {
    const card = coach(page, 'Обучение пройдено')
    await expect(card).toBeVisible()
    await card.getByRole('button', { name: 'Готово' }).click()
    await expect(page.getByText('Обучение пройдено').first()).toBeVisible()
    await expect.poll(async () => (await tourState(request)).tour.status).toBe('completed')
    const state = await tourState(request)
    const done = state.checklist.items.map((item: { key: string }) => item.key)
    expect(done).toEqual(
      expect.arrayContaining([
        'project_created',
        'text_source_added',
        'document_uploaded',
        'diagram_built',
        'question_answered',
        'assumption_accepted',
        'project_shared',
      ]),
    )
  })
  await context.close()
})

test('«Я уже знаком»: нет оверлеев, после перезагрузки приветствия нет', async ({
  browser,
  baseURL,
}) => {
  const { page, request, context } = await newPlayer(browser, baseURL)
  await page.goto('/projects')
  const welcome = page.getByRole('dialog', { name: 'Добро пожаловать в Архитектор' })
  await expect(welcome).toBeVisible()
  await welcome.getByRole('button', { name: 'Я уже знаком' }).click()
  await expect(welcome).toBeHidden()
  await expect(page.getByText('Обучение всегда можно пройти в меню аккаунта')).toBeVisible()
  await expect.poll(async () => (await tourState(request)).tour.status).toBe('dismissed')
  await expect(page.locator('[data-tour-layer]')).toHaveCount(0)

  await page.reload()
  await expect(page.getByRole('heading', { name: 'Проекты' })).toBeVisible()
  await page.waitForTimeout(1200)
  await expect(page.getByRole('dialog')).toHaveCount(0)
  await context.close()
})

test('перезагрузка на шаге 7 продолжает тур с шага 7', async ({ browser, baseURL }) => {
  test.setTimeout(120_000)
  const player = await sharedPlayer(browser, baseURL)
  const { page, request } = player
  const projectId = await seedTour(player, 'question.answer', { text: true })
  await send(request, 'post', `/api/v1/projects/${projectId}/runs`, { mode: 'build' })
  await expect
    .poll(async () => (await (await request.get(`/api/v1/projects/${projectId}`)).json()).status, {
      timeout: 60_000,
    })
    .toBe('needs_answers')

  await page.goto(`/projects/${projectId}`)
  const card = coach(page, 'Ответьте на вопрос')
  await expect(card).toBeVisible()
  await expect(card).toContainText('Шаг 7 из 11')
  await page.reload()
  await expect(coach(page, 'Ответьте на вопрос')).toBeVisible()
  await expect(coach(page, 'Ответьте на вопрос')).toContainText('Шаг 7 из 11')
  expect((await tourState(request)).tour.step).toBe('question.answer')
  await page.close()
})

test('свёрнутые панели «Источники» и «Вопросы» разворачиваются туром', async ({
  browser,
  baseURL,
}) => {
  test.setTimeout(120_000)
  const player = await sharedPlayer(browser, baseURL)
  const { page, request } = player
  const projectId = await seedTour(player, 'sources.sample', { text: true })
  // Пока тур не мешает: отложим его, свернём обе панели, затем вернём.
  await send(request, 'patch', '/api/v1/me/onboarding/tour', { status: 'dismissed' })
  await page.goto(`/projects/${projectId}`)
  await page
    .getByRole('region', { name: 'Источники' })
    .getByRole('button', { name: 'Свернуть панель' })
    .click()
  await page
    .getByRole('region', { name: 'Вопросы' })
    .getByRole('button', { name: 'Свернуть панель' })
    .click()
  await expect(page.getByRole('button', { name: 'Развернуть: Источники' })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Развернуть: Вопросы' })).toBeVisible()

  await send(request, 'post', '/api/v1/me/onboarding/tour/restart')
  await send(request, 'patch', '/api/v1/me/onboarding/tour', {
    step: 'sources.sample',
    project_id: projectId,
  })
  await page.reload()
  await expect(coach(page, 'Добавьте источник')).toBeVisible()
  await expect(page.getByRole('region', { name: 'Источники' })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Добавить источник' })).toBeVisible()

  // Вопросы свёрнуты; шаг 7 разворачивает их.
  await send(request, 'post', `/api/v1/projects/${projectId}/runs`, { mode: 'build' })
  await expect
    .poll(async () => (await (await request.get(`/api/v1/projects/${projectId}`)).json()).status, {
      timeout: 60_000,
    })
    .toBe('needs_answers')
  await send(request, 'patch', '/api/v1/me/onboarding/tour', { step: 'question.answer' })
  await page.reload()
  await expect(coach(page, 'Ответьте на вопрос')).toBeVisible()
  await expect(page.getByRole('region', { name: 'Вопросы' })).toBeVisible()
  await expect(page.locator('[data-question-id]').first()).toBeVisible()
  await page.close()
})

test('fail-early: «Повторить» запускает прогон снова, «Пропустить главу» ведёт к шагу 10', async ({
  browser,
  baseURL,
}) => {
  test.setTimeout(150_000)
  const player = await sharedPlayer(browser, baseURL)
  const { page } = player
  const projectId = await seedTour(player, 'run.start', {
    text: 'Заявитель подаёт заявку, сетевая организация её проверяет.',
    markers: '[[mock:fail-early]]',
  })
  await page.goto(`/projects/${projectId}`)
  await expect(coach(page, 'Постройте схему')).toBeVisible()
  await page.getByRole('banner').getByRole('button', { name: 'Построить схему' }).click()

  const runStarts: string[] = []
  page.on('request', (request) => {
    if (request.method() === 'POST' && request.url().endsWith(`/projects/${projectId}/runs`)) {
      runStarts.push(request.url())
    }
  })
  const failed = coach(page, 'Прогон не удался')
  await expect(failed).toBeVisible({ timeout: 60_000 })
  expect(runStarts).toHaveLength(1)
  await expect(failed).toContainText('Модель не ответила. Попробуем ещё раз?')
  await failed.getByRole('button', { name: 'Повторить' }).click()
  // «Повторить» запустил второй прогон (а не просто перерисовал текст): шаг 6 заново, затем та же ошибка.
  await expect.poll(() => runStarts.length).toBe(2)
  await expect(coach(page, 'Модель работает')).toBeVisible()
  await expect(coach(page, 'Прогон не удался')).toBeVisible({ timeout: 60_000 })
  await coach(page, 'Прогон не удался').getByRole('button', { name: 'Пропустить главу' }).click()
  await expect(coach(page, 'Поделитесь схемой')).toBeVisible()
  await page.close()
})

test('fail-structuring: вопросы есть, схемы нет — шаги 7–8, шаг 9 пропущен', async ({
  browser,
  baseURL,
}) => {
  test.setTimeout(180_000)
  const player = await sharedPlayer(browser, baseURL)
  const { page } = player
  const projectId = await seedTour(player, 'run.start', {
    text: true,
    markers: '[[mock:fail-structuring]]',
  })
  await page.goto(`/projects/${projectId}`)
  await page.getByRole('banner').getByRole('button', { name: 'Построить схему' }).click()

  await expect(coach(page, 'Ответьте на вопрос')).toBeVisible({ timeout: 90_000 })
  const first = page.locator('[data-question-id]').first()
  await first.getByRole('button', { name: 'Ответить', exact: true }).click()
  await first.getByRole('textbox').fill('Акт готовит сетевая организация.')
  await first.getByRole('button', { name: 'Отправить ответ' }).click()

  await expect(coach(page, 'Или примите допущение')).toBeVisible()
  await page
    .locator('[data-question-id]')
    .filter({ has: page.getByRole('button', { name: 'Игнорировать' }) })
    .first()
    .getByRole('button', { name: 'Игнорировать' })
    .click()

  await expect(coach(page, 'Поделитесь схемой')).toBeVisible()
  await expect(coach(page, 'Посмотрите схему')).toHaveCount(0)
  await page.close()
})

test('no-questions: вопросов нет — шаги 7–8 пропущены, карточка объясняет', async ({
  browser,
  baseURL,
}) => {
  test.setTimeout(150_000)
  const player = await sharedPlayer(browser, baseURL)
  const { page } = player
  const projectId = await seedTour(player, 'run.start', {
    text: 'Заявитель подаёт заявку, сетевая организация проверяет её и выставляет счёт.',
    markers: '[[mock:no-questions]]',
  })
  await page.goto(`/projects/${projectId}`)
  await page.getByRole('banner').getByRole('button', { name: 'Построить схему' }).click()

  const card = coach(page, 'Вопросов нет')
  await expect(card).toBeVisible({ timeout: 90_000 })
  await expect(card).toContainText('Модель всё поняла сама — вопросов нет')
  await card.getByRole('button', { name: 'Далее' }).click()
  await expect(coach(page, 'Посмотрите схему')).toBeVisible()
  await expect(coach(page, 'Ответьте на вопрос')).toHaveCount(0)
  await page.close()
})

test('«Примеры» есть в меню источников и вне тура', async ({ page }) => {
  await page.goto('/projects')
  await page.getByRole('button', { name: 'Новый проект' }).first().click()
  const dialog = page.getByRole('dialog', { name: 'Новый проект' })
  await dialog
    .getByRole('textbox', { name: 'Название' })
    .fill(`Примеры ${randomUUID().slice(0, 6)}`)
  await dialog.getByRole('button', { name: 'Создать проект' }).click()
  await expect(page).toHaveURL(/\/projects\/[\w-]+$/)
  await expect(page.locator('[data-tour-layer]')).toHaveCount(0)
  await page.getByRole('button', { name: 'Добавить источник' }).click()
  const menu = page.getByRole('menu')
  await expect(menu.getByText('Примеры')).toBeVisible()
  await menu.getByRole('menuitem', { name: /Голосовая заметка — согласование/ }).click()
  await expect(page.getByRole('region', { name: 'Источники' })).toContainText('согласование заявки')
})
