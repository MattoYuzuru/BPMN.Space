import { randomUUID } from 'node:crypto'
import {
  type APIResponse,
  type Browser,
  type BrowserContext,
  expect,
  type Page,
  request as playwrightRequest,
  type APIRequestContext as RequestContext,
  test,
} from '@playwright/test'
import { createExampleProject, dragElement, runViaApi } from './support'

/**
 * Чек-лист «Начало работы»: пункт меню, плашка, панель, переход к пункту с подсказкой,
 * уведомления. У каждого сценария свой новый пользователь: пункты копятся, общий пользователь из
 * global-setup тур отклонил и чек-лист скрыл. Нужны аккаунты и включённый онбординг.
 */
// Регистрация новых пользователей упирается в лимит запросов по IP: запас на ожидание.
test.describe.configure({ timeout: 150_000 })

test.beforeEach(async ({ request }) => {
  const session = await (await request.get('/api/v1/auth/session')).json()
  test.skip(!session.auth_enabled, 'Онбординг работает только с аккаунтами')
  const state = await (await request.get('/api/v1/me/onboarding')).json()
  test.skip(!state.enabled, 'Онбординг на стенде выключен')
})

interface Newcomer {
  page: Page
  api: RequestContext
}

/**
 * Вход и регистрация ограничены по IP (20 в минуту): сценариев много, поэтому на «Слишком много
 * запросов» ждём `Retry-After` и повторяем.
 */
async function postThrottled(send: () => Promise<APIResponse>) {
  const deadline = Date.now() + 70_000
  for (;;) {
    const response = await send()
    if (response.ok()) return
    if (response.status() !== 429) throw new Error(`Запрос отклонён: ${response.status()}`)
    const wait = (Number(response.headers()['retry-after'] ?? 10) + 1) * 1000
    if (Date.now() + wait > deadline) throw new Error('Лимит запросов не снялся за 70 с')
    await new Promise((resolve) => setTimeout(resolve, wait))
  }
}

/** Новый пользователь: регистрация, вход, отказ от тура (чек-лист остаётся видимым). */
async function newcomer(
  browser: Browser,
  baseURL: string | undefined,
  { viewport = { width: 1440, height: 900 }, track = true } = {},
): Promise<Newcomer> {
  const api = await playwrightRequest.newContext({ baseURL })
  const { csrf_token: csrf } = await (await api.get('/api/v1/auth/csrf')).json()
  const headers = { 'X-CSRF-Token': csrf }
  const email = `checklist-${randomUUID()}@example.com`
  const password = `e2e-${randomUUID()}`
  await postThrottled(() =>
    api.post('/api/v1/auth/register', { data: { email, password }, headers }),
  )
  await postThrottled(() =>
    api.post('/api/v1/auth/session/login', { form: { username: email, password }, headers }),
  )
  const dismissed = await api.patch('/api/v1/me/onboarding/tour', {
    data: { status: 'dismissed' },
    headers,
  })
  expect(dismissed.ok()).toBe(true)
  const context = await browser.newContext({
    baseURL,
    locale: 'ru-RU',
    viewport,
    storageState: await api.storageState(),
  })
  if (track) {
    opened.push({ context, api })
  }
  return { page: await context.newPage(), api }
}

/** Контексты сценариев, которые надо закрыть после теста (общий пользователь серии закрывается сам). */
const opened: { context: BrowserContext; api: RequestContext }[] = []

test.afterEach(async () => {
  for (const { context, api } of opened.splice(0)) {
    await context.close()
    await api.dispose()
  }
})

const pill = (page: Page) => page.getByRole('button', { name: /^Начало работы, выполнено/ })

async function openMenuItem(page: Page) {
  await page.getByRole('button', { name: 'Аккаунт' }).click()
  await page.getByRole('menuitem', { name: /Начало работы/ }).click()
}

test('меню, панель, плашка и перезапуск обучения', async ({ browser, baseURL }) => {
  const { page, api } = await newcomer(browser, baseURL)
  const panel = page.getByRole('dialog', { name: 'Начало работы' })

  await test.step('меню аккаунта и панель: 4 группы, 12 пунктов, отметить руками нельзя', async () => {
    await page.goto('/')

    await page.getByRole('button', { name: 'Аккаунт' }).click()
    const item = page.getByRole('menuitem', { name: /Начало работы/ })
    await expect(item).toContainText('0/12')
    // между почтой и «Выйти»
    const items = page.getByRole('menuitem')
    await expect(items.first()).toContainText('Начало работы')
    await expect(items.last()).toHaveText('Выйти')
    await item.click()

    await expect(panel).toBeVisible()
    await expect(panel.getByText('0 из 12')).toBeVisible()
    await expect(panel.getByRole('heading', { level: 3 })).toHaveText([
      'Источники',
      'Анализ',
      'Схема',
      'Команда',
    ])
    await expect(panel.getByRole('listitem')).toHaveCount(12)
    await expect(panel.getByRole('checkbox')).toHaveCount(0)
    await expect(panel.getByRole('button', { name: 'Пройти обучение заново' })).toBeVisible()
    await page.keyboard.press('Escape')
    await expect(panel).toBeHidden()
  })

  await test.step('плашка: на экране проектов, не в рабочем месте; «Скрыть» убирает её, пункт меню остаётся', async () => {
    const projectId = await createExampleProject(api)

    await page.goto('/')
    await expect(pill(page)).toBeVisible()
    await expect(pill(page)).toContainText('1/12')

    // в рабочем пространстве плашки нет
    await page.goto(`/projects/${projectId}`)
    await expect(page.getByRole('region', { name: 'Источники' })).toBeVisible()
    await expect(pill(page)).toHaveCount(0)

    await page.goto('/')
    await pill(page).click()
    await panel.getByRole('button', { name: 'Скрыть чек-лист' }).click()
    await expect(panel.getByRole('button', { name: 'Показывать прогресс' })).toBeVisible()
    await page.keyboard.press('Escape')
    await expect(panel).toBeHidden()
    await expect(pill(page)).toHaveCount(0)

    // пункт меню остаётся и ведёт в ту же панель
    await openMenuItem(page)
    await expect(panel).toBeVisible()
    await panel.getByRole('button', { name: 'Показывать прогресс' }).click()
    await page.keyboard.press('Escape')
    await expect(pill(page)).toBeVisible()

    // состояние сохранилось на сервере
    await page.reload()
    await expect(pill(page)).toBeVisible()
  })

  await test.step('«Пройти обучение заново»: перезапуск на сервере и закрытие панели', async () => {
    await page.goto('/')
    await pill(page).click()

    const restarted = page.waitForResponse(
      (response) =>
        response.url().endsWith('/api/v1/me/onboarding/tour/restart') &&
        response.request().method() === 'POST',
    )
    await panel.getByRole('button', { name: 'Пройти обучение заново' }).click()
    expect((await restarted).ok()).toBe(true)
    await expect(panel).toBeHidden()

    const state = await (await api.get('/api/v1/me/onboarding')).json()
    expect(state.tour.status).toBe('active')
    expect(state.tour.step).toBe('project.create')
    // тур действительно пошёл: карточка первого шага на экране, плашки нет
    await expect(page.getByRole('dialog', { name: 'Создайте проект' })).toBeVisible()
    await expect(pill(page)).toHaveCount(0)
  })
})

test('плашка не перекрывает экран проектов на 1024 и 2560 px', async ({ browser, baseURL }) => {
  const { page, api } = await newcomer(browser, baseURL)
  for (let index = 0; index < 4; index += 1) await createExampleProject(api)

  for (const viewport of [
    { width: 1024, height: 768 },
    { width: 2560, height: 1440 },
  ]) {
    await test.step(`${viewport.width} px`, async () => {
      await page.setViewportSize(viewport)
      // Только свои проекты: список конечный, до конца страницы можно дойти (в «Все» он подгружается).
      await page.goto('/projects?scope=own')
      await expect(pill(page)).toBeVisible()
      await expect(page.locator('section[aria-label="Проекты"] a[href^="/projects/"]')).toHaveCount(
        4,
      )

      const pillBox = await pill(page).boundingBox()
      expect(pillBox).not.toBeNull()
      expect(pillBox?.x).toBeGreaterThanOrEqual(0)
      expect((pillBox?.y ?? 0) + (pillBox?.height ?? 0)).toBeLessThanOrEqual(viewport.height)

      /** Элементы экрана проектов, на которые легла плашка (`selector`). */
      const covered = async (selector: string) => {
        const found: string[] = []
        for (const element of await page.locator(selector).all()) {
          const box = await element.boundingBox()
          if (!box || !pillBox || box.width === 0 || box.height === 0) continue
          const crosses =
            box.x < pillBox.x + pillBox.width &&
            box.x + box.width > pillBox.x &&
            box.y < pillBox.y + pillBox.height &&
            box.y + box.height > pillBox.y
          if (crosses) found.push(((await element.textContent()) ?? '').trim().slice(0, 40))
        }
        return found
      }

      // В начале страницы плашка не закрывает ни одной кнопки и поля.
      expect(await covered('main button, main [role="radio"], main [role="searchbox"]')).toEqual([])
      // В конце страницы под плашкой нет и карточек: хватает нижнего отступа экрана.
      await page.mouse.move(viewport.width / 2, viewport.height / 2)
      await page.mouse.wheel(0, 100_000)
      await page.waitForTimeout(500)
      expect(await covered('main a, main button')).toEqual([])
    })
  }
})

/**
 * Пункты, которые отмечает сама работа, идут одним пользователем подряд: регистрация ограничена
 * по IP, а пункты друг другу не мешают (у каждого свой проект и своё действие).
 */
test('финал тура: «Открыть чек-лист» открывает панель', async ({ browser, baseURL }) => {
  const { page, api } = await newcomer(browser, baseURL)
  const { csrf_token: csrf } = await (await api.get('/api/v1/auth/csrf')).json()
  const headers = { 'X-CSRF-Token': csrf }
  expect((await api.post('/api/v1/me/onboarding/tour/restart', { headers })).ok()).toBe(true)
  const stepped = await api.patch('/api/v1/me/onboarding/tour', {
    data: { step: 'finish' },
    headers,
  })
  expect(stepped.ok()).toBe(true)
  await page.goto('/')
  await page.getByRole('button', { name: 'Открыть чек-лист' }).click()
  await expect(page.getByRole('dialog', { name: 'Начало работы' })).toBeVisible()
})

test.describe('переход к пункту и уведомления', () => {
  test.describe.configure({ mode: 'serial' })
  let user: Newcomer

  test.beforeAll(async ({ browser, baseURL }) => {
    user = await newcomer(browser, baseURL, { track: false })
  })

  test.afterAll(async () => {
    await user.page.context().close()
    await user.api.dispose()
  })

  test('действие вне тура: уведомление «Готово: …», пункт зачёркнут в панели без перезагрузки', async () => {
    const { page } = user
    await page.goto('/')
    await expect(pill(page)).toContainText('0/12')

    await page.getByRole('button', { name: 'Новый проект' }).first().click()
    const dialog = page.getByRole('dialog', { name: 'Новый проект' })
    await dialog.getByRole('textbox', { name: 'Название' }).fill('Приёмка оборудования')
    await dialog.getByRole('button', { name: 'Создать проект' }).click()
    await expect(page).toHaveURL(/\/projects\//)

    const toast = page.getByText('Готово: Создать проект')
    await expect(toast).toBeVisible()
    await expect(page.getByText('Начало работы — 1 из 12')).toBeVisible()

    // «Открыть» в уведомлении открывает панель: пункт уже отмечен
    // Уведомления лежат стопкой: нужное нажимаем напрямую, не целясь в перекрытую кнопку.
    await page.getByRole('button', { name: 'Открыть', exact: true }).dispatchEvent('click')
    const panel = page.getByRole('dialog', { name: 'Начало работы' })
    await expect(panel.getByText('1 из 12')).toBeVisible()
    const row = panel.locator('[data-item="project_created"]')
    await expect(row).toContainText('выполнено')
    await expect(row.getByRole('button')).toHaveCount(0)
  })

  test('«Ответить на вопрос»: переход к карточке, подсказка, ответ — уведомление и подсказка уходит', async () => {
    const { page, api } = user
    const projectId = await createExampleProject(api)
    await runViaApi(api, projectId, 'analyze')

    await page.goto('/')
    await pill(page).click()
    const panel = page.getByRole('dialog', { name: 'Начало работы' })
    await panel.getByRole('button', { name: /Ответить на вопрос/ }).click()

    await expect(page).toHaveURL(new RegExp(`/projects/${projectId}\\?question=`))
    const hint = page.getByRole('dialog', { name: 'Подсказка' })
    await expect(hint).toContainText(
      'Нажмите «Ответить» и напишите ответ — он станет новым источником.',
    )
    const questionId = new URL(page.url()).searchParams.get('question')
    const card = page.locator(`[data-question-id="${questionId}"]`)
    await expect(card.getByRole('button', { name: 'Ответить', exact: true })).toBeVisible()

    await card.getByRole('button', { name: 'Ответить', exact: true }).click()
    await card
      .getByRole('textbox')
      .fill('Уведомление направляет сетевая организация через личный кабинет заявителя.')
    await card.getByRole('button', { name: 'Отправить ответ' }).click()

    await expect(page.getByText('Готово: Ответить на вопрос')).toBeVisible()
    await expect(hint).toBeHidden()
  })

  test('«Изменить схему вручную»: подсказка на холсте, правка — уведомление', async () => {
    const { page, api } = user
    const projectId = await createExampleProject(api)
    await runViaApi(api, projectId, 'build')

    await page.goto('/')
    await pill(page).click()
    await page
      .getByRole('dialog', { name: 'Начало работы' })
      .getByRole('button', { name: /Изменить схему вручную/ })
      .click()

    await expect(page).toHaveURL(new RegExp(`/projects/${projectId}`))
    await expect(page.getByRole('dialog', { name: 'Подсказка' })).toContainText(
      'Подвигайте или переименуйте любой элемент схемы',
    )
    await page.locator('.djs-container').waitFor()
    await page
      .getByRole('dialog', { name: 'Подсказка' })
      .getByRole('button', { name: 'Понятно' })
      .click()
    await page.getByRole('button', { name: 'Вписать в окно' }).click()
    await page.waitForTimeout(600)
    await dragElement(page, 'Task_Inspection', 40, 30)
    await expect(page.getByText('Готово: Изменить схему вручную')).toBeVisible({ timeout: 15_000 })
  })

  test('«Поделиться проектом»: подсказка на кнопке, ссылка — уведомление', async () => {
    const { page, api } = user
    const projectId = await createExampleProject(api)

    await page.goto('/')
    await pill(page).click()
    await page
      .getByRole('dialog', { name: 'Начало работы' })
      .getByRole('button', { name: /Поделиться проектом/ })
      .click()

    await expect(page).toHaveURL(new RegExp(`/projects/${projectId}`))
    const hint = page.getByRole('dialog', { name: 'Подсказка' })
    await expect(hint).toContainText('Нажмите «Поделиться» и создайте ссылку на схему.')

    // клик по самому элементу закрывает подсказку и открывает окно
    await page.getByRole('button', { name: 'Поделиться', exact: true }).click()
    const share = page.getByRole('dialog', { name: 'Поделиться проектом' })
    await share.getByRole('button', { name: 'Создать ссылку' }).click()
    await expect(share.getByRole('textbox', { name: 'Ссылка' })).toBeVisible()
    await expect(page.getByText('Готово: Поделиться проектом')).toBeVisible()
  })
})
