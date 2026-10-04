import { randomUUID } from 'node:crypto'
import { type Browser, expect, type Page, test } from '@playwright/test'
import { createExampleProject, dragElement, runViaApi } from './support'

/**
 * Общий доступ: ссылка на просмотр, приглашение редактора, отзыв. Нужны аккаунты на стенде.
 * Владелец — тестовый пользователь из global-setup; гости и новые пользователи — свежие контексты.
 */
test.beforeEach(async ({ request }) => {
  const session = await (await request.get('/api/v1/auth/session')).json()
  test.skip(!session.auth_enabled, 'Общий доступ работает только с аккаунтами')
})

const SIGNED_OUT = { cookies: [], origins: [] }

/** Чистый браузерный контекст без входа (с теми же адресом и языком, что у основного). */
async function freshPage(browser: Browser, baseURL: string | undefined): Promise<Page> {
  const context = await browser.newContext({
    baseURL,
    locale: 'ru-RU',
    viewport: { width: 1440, height: 900 },
    storageState: SIGNED_OUT,
  })
  return context.newPage()
}

/** Владелец создаёт ссылку выбранной роли в диалоге «Поделиться» и возвращает её адрес. */
async function createLink(page: Page, access: 'Просмотр' | 'Редактирование'): Promise<string> {
  await page.getByRole('button', { name: 'Поделиться' }).click()
  const dialog = page.getByRole('dialog', { name: 'Поделиться проектом' })
  await dialog.getByRole('radio', { name: access }).click()
  await dialog.getByRole('button', { name: 'Создать ссылку' }).click()
  const field = dialog.getByRole('textbox', { name: 'Ссылка' })
  await expect(field).toBeVisible()
  const url = await field.inputValue()
  expect(url).toMatch(/\/share\/[\w-]+$/)
  return url
}

async function readyProject(request: Parameters<typeof createExampleProject>[0]) {
  const id = await createExampleProject(request)
  await runViaApi(request, id, 'build')
  return id
}

test('ссылка на просмотр: гость видит схему и не видит ни одного действия записи', async ({
  page,
  request,
  browser,
  baseURL,
}) => {
  const id = await readyProject(request)
  await page.goto(`/projects/${id}`)
  const url = await createLink(page, 'Просмотр')

  const guest = await freshPage(browser, baseURL)
  await guest.goto(url)

  await expect(guest.getByRole('region', { name: 'Вопросы' })).toBeVisible()
  await expect(guest.locator('.djs-container')).toBeVisible()
  await expect(guest.locator('[data-element-id]').first()).toBeVisible()
  await expect(guest.getByText('Только просмотр').first()).toBeVisible()
  await expect(guest.getByRole('link', { name: 'Войти' })).toBeVisible()
  await expect(guest.getByRole('button', { name: 'Скачать схему' })).toBeVisible()
  // Источники читаются, но менять их нельзя.
  await expect(guest.getByRole('region', { name: 'Источники' })).toBeVisible()

  for (const name of [
    'Анализ',
    'Построить схему',
    'Добавить источник',
    'Переименовать',
    'Поделиться',
  ]) {
    await expect(guest.getByRole('button', { name, exact: true })).toHaveCount(0)
  }
  await expect(guest.getByRole('button', { name: 'Ответить', exact: true })).toHaveCount(0)
  // Схему не перетащить: правка не запускает сохранение.
  await guest.getByRole('button', { name: 'Вписать в окно' }).click()
  await guest.waitForTimeout(600)
  await dragElement(guest, 'Task_Inspection', 40, 30)
  await guest.waitForTimeout(2500)
  await expect(guest.getByText(/Схема сохранена|Сохраняется|Сохранено/)).toHaveCount(0)
  // Закрытые экраны гостю по-прежнему закрыты.
  await guest.goto(`/projects/${id}`)
  await expect(guest).toHaveURL(/\/login\?redirect=/)
  await guest.context().close()
})

test('приглашение редактора: регистрация, принятие, правка без права удаления', async ({
  page,
  request,
  browser,
  baseURL,
}) => {
  const id = await readyProject(request)
  await page.goto(`/projects/${id}`)
  const url = await createLink(page, 'Редактирование')
  await page.keyboard.press('Escape')

  const guest = await freshPage(browser, baseURL)
  await guest.goto(url)
  await expect(guest.getByRole('heading', { name: 'Приглашение в проект' })).toBeVisible()
  await expect(guest.getByRole('button', { name: 'Принять приглашение' })).toHaveCount(0)
  await guest.getByRole('link', { name: 'Войти, чтобы принять' }).click()
  await expect(guest).toHaveURL(/\/login\?redirect=%2Fshare%2F/)

  const email = `invitee-${randomUUID()}@example.com`
  await guest.getByRole('radio', { name: 'Регистрация' }).click()
  await guest.getByRole('textbox', { name: 'Почта' }).fill(email)
  await guest.getByLabel('Пароль', { exact: true }).fill(`pw-${randomUUID()}`)
  await guest.keyboard.press('Enter')

  // После входа — снова на приглашении, уже с кнопкой принятия.
  await expect(guest.getByRole('button', { name: 'Принять приглашение' })).toBeVisible()
  await guest.getByRole('button', { name: 'Принять приглашение' }).click()
  await expect(guest).toHaveURL(new RegExp(`/projects/${id}$`))
  await expect(guest.getByText('Приглашение принято')).toBeVisible()

  // Редактор правит: доступны запуск и правка схемы, но нет «Поделиться» и «Только просмотр».
  await expect(guest.getByRole('button', { name: 'Построить схему' })).toBeVisible()
  await expect(guest.getByText('Только просмотр')).toHaveCount(0)
  await expect(guest.getByRole('button', { name: 'Поделиться' })).toHaveCount(0)
  await guest.locator('.djs-container').waitFor()
  await guest.getByRole('button', { name: 'Вписать в окно' }).click()
  await guest.waitForTimeout(600)
  await dragElement(guest, 'Task_Inspection', 40, 30)
  await expect(guest.getByText('Схема сохранена')).toBeVisible({ timeout: 15_000 })

  // В списке проект лежит в «Общих» и не удаляется.
  await guest.goto('/projects')
  await guest.getByRole('radio', { name: 'Общие' }).click()
  await expect(guest).toHaveURL(/scope=shared/)
  const card = guest.getByRole('link', { name: 'Технологическое присоединение (ПП № 861)' })
  await expect(card).toBeVisible()
  await expect(card.getByText('Общий')).toBeVisible()
  // В «Общих» нет демо-примера: он лежит в «Примерах».
  await expect(
    guest.getByRole('link', { name: 'Технологическое присоединение к электросетям' }),
  ).toHaveCount(0)
  await expect(guest.getByRole('button', { name: 'Действия с проектом' })).toHaveCount(0)
  await guest.getByRole('radio', { name: 'Мои' }).click()
  await expect(guest.getByText('Своих проектов пока нет')).toBeVisible()

  // Владелец видит нового участника и может его убрать.
  await page.getByRole('button', { name: 'Поделиться' }).click()
  const dialog = page.getByRole('dialog', { name: 'Поделиться проектом' })
  await dialog.getByRole('tab', { name: /Участники/ }).click()
  await expect(dialog.getByText(email)).toBeVisible()
  await dialog.getByRole('button', { name: 'Убрать участника' }).click()
  await page.getByRole('alertdialog').getByRole('button', { name: 'Убрать' }).click()
  await expect(dialog.getByText('Участников пока нет')).toBeVisible()
  await guest.goto(`/projects/${id}`)
  await expect(guest.getByText('Проект не найден')).toBeVisible()
  await guest.context().close()
})

test('отозванная ссылка перестаёт открываться', async ({ page, request, browser, baseURL }) => {
  const id = await readyProject(request)
  await page.goto(`/projects/${id}`)
  const url = await createLink(page, 'Просмотр')

  const guest = await freshPage(browser, baseURL)
  await guest.goto(url)
  await expect(guest.getByRole('region', { name: 'Вопросы' })).toBeVisible()

  // Адрес больше нигде не показывается: в списке только роль и срок.
  const dialog = page.getByRole('dialog', { name: 'Поделиться проектом' })
  await dialog.getByRole('button', { name: 'Создать другую' }).click()
  const links = dialog.getByRole('list', { name: 'Действующие ссылки' })
  await expect(links.getByRole('listitem')).toHaveCount(1)
  await expect(dialog.getByRole('textbox')).toHaveCount(0)

  await links.getByRole('button', { name: 'Отозвать ссылку' }).click()
  await page
    .getByRole('alertdialog', { name: 'Отозвать ссылку?' })
    .getByRole('button', { name: 'Отозвать' })
    .click()
  await expect(dialog.getByText('Ссылок пока нет')).toBeVisible()

  await guest.reload()
  await expect(guest.getByText('Ссылка недействительна')).toBeVisible()
  await expect(guest.getByRole('region', { name: 'Вопросы' })).toHaveCount(0)
  await guest.context().close()
})
