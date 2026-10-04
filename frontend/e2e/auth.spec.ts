import { randomUUID } from 'node:crypto'
import { expect, type Page, test } from '@playwright/test'
import { DEMO_PROJECT_ID } from './support'

/** Экран входа и права доступа. Первые сценарии идут как гость — без сохранённого входа. */
test.describe('гость', () => {
  test.use({ storageState: { cookies: [], origins: [] } })

  test.beforeEach(async ({ request }) => {
    const session = await (await request.get('/api/v1/auth/session')).json()
    test.skip(!session.auth_enabled, 'На стенде без аккаунтов вход не нужен')
  })

  async function fillAndSubmit(page: Page, email: string, password: string) {
    await page.getByRole('textbox', { name: 'Почта' }).fill(email)
    await page.getByLabel('Пароль', { exact: true }).fill(password)
    await page.keyboard.press('Enter')
  }

  test('закрытый адрес ведёт на вход и после входа возвращает назад', async ({ page }) => {
    await page.goto(`/projects/${DEMO_PROJECT_ID}`)
    await expect(page).toHaveURL(/\/login\?redirect=%2Fprojects%2F/)
    await expect(page.getByRole('heading', { name: 'Архитектор' })).toBeVisible()
    await expect(page.getByRole('textbox', { name: 'Почта' })).toBeFocused()

    await page.getByRole('radio', { name: 'Регистрация' }).click()
    await fillAndSubmit(page, `e2e-${randomUUID()}@example.com`, `pw-${randomUUID()}`)

    await expect(page).toHaveURL(new RegExp(`/projects/${DEMO_PROJECT_ID}$`))
    await expect(page.getByRole('region', { name: 'Вопросы' })).toBeVisible()
  })

  test('ошибки входа и регистрации показаны по-русски под полями', async ({ page }) => {
    await page.goto('/login')

    await page.getByRole('button', { name: 'Войти' }).click()
    await expect(page.getByText('Укажите почту')).toBeVisible()
    await expect(page.getByText('Введите пароль')).toBeVisible()

    await fillAndSubmit(page, 'nobody@example.com', 'wrong-password-123')
    await expect(page.getByText('Неверная почта или пароль')).toBeVisible()

    await page.getByRole('radio', { name: 'Регистрация' }).click()
    await fillAndSubmit(page, 'nobody@example.com', 'short')
    await expect(page.getByText(/Пароль — от 12 символов/)).toBeVisible()
  })

  test('пароль можно показать, адрес возврата чужого сайта игнорируется', async ({ page }) => {
    await page.goto('/login?redirect=https://evil.example/')
    const password = page.getByLabel('Пароль', { exact: true })
    await password.fill('secret-secret')
    await expect(password).toHaveAttribute('type', 'password')
    await page.getByRole('button', { name: 'Показать пароль' }).click()
    await expect(password).toHaveAttribute('type', 'text')
    await expect(page).toHaveURL(/\/login$/)
  })

  test('меню аккаунта: почта и выход', async ({ page }) => {
    const email = `e2e-${randomUUID()}@example.com`
    await page.goto('/login')
    await page.getByRole('radio', { name: 'Регистрация' }).click()
    await fillAndSubmit(page, email, `pw-${randomUUID()}`)
    await expect(page.getByRole('heading', { name: 'Проекты' })).toBeVisible()

    await page.getByRole('button', { name: 'Аккаунт' }).click()
    await expect(page.getByRole('menu')).toContainText(email)
    await page.getByRole('menuitem', { name: 'Выйти' }).click()

    await expect(page).toHaveURL(/\/login/)
    await page.goto('/')
    await expect(page).toHaveURL(/\/login/)
  })
})

test.describe('вошедший пользователь', () => {
  test('демо-проект открыт только для чтения', async ({ page }) => {
    await page.goto(`/projects/${DEMO_PROJECT_ID}`)
    await expect(page.getByRole('region', { name: 'Вопросы' })).toBeVisible()
    await expect(page.getByText('Только просмотр').first()).toBeVisible()
    await expect(page.getByRole('button', { name: 'Анализ', exact: true })).toHaveCount(0)
    await expect(page.getByRole('button', { name: 'Построить схему' })).toHaveCount(0)
    await expect(page.getByRole('button', { name: 'Добавить источник' })).toHaveCount(0)
    await expect(page.getByRole('button', { name: 'Ответить', exact: true })).toHaveCount(0)
    await expect(page.getByRole('button', { name: 'Переименовать' })).toHaveCount(0)
  })

  test('в списке демо-проект помечен как пример и не удаляется', async ({ page }) => {
    await page.goto('/projects?q=электросетям')
    const card = page.getByRole('link', { name: /электросетям/ })
    await expect(card).toBeVisible()
    await expect(card.getByText('Пример')).toBeVisible()
    await expect(page.getByRole('button', { name: 'Действия с проектом' })).toHaveCount(0)
  })
})
