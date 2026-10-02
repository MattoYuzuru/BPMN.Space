import { expect, test } from '@playwright/test'
import { createExampleProject, DEMO_PROJECT_ID } from './support'

test('тёмная тема переключается и запоминается', async ({ page }) => {
  await page.goto('/')
  await page.getByRole('radio', { name: 'Тёмная' }).click()
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark')
  await page.reload()
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark')
  await page.getByRole('radio', { name: 'Светлая' }).click()
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'light')
})

test('палитра команд: Ctrl+K, переход и команды проекта', async ({ page, request }) => {
  const projectId = await createExampleProject(request)
  await page.goto(`/projects/${projectId}`)
  await expect(page.getByRole('region', { name: 'Вопросы' })).toBeVisible()
  // Устройство «Desktop Chrome» — Windows: модификатор палитры здесь Ctrl.
  await page.keyboard.press('Control+k')
  const palette = page.getByRole('dialog', { name: 'Палитра команд' })
  await expect(palette).toBeVisible()
  await expect(palette.getByRole('option', { name: 'Запустить анализ' })).toBeVisible()
  await palette.getByRole('combobox').fill('стайлгайд')
  await page.keyboard.press('Enter')
  await expect(page).toHaveURL(/\/styleguide/)
})

test('новый пустой проект: онбординг и текстовый источник', async ({ page }) => {
  await page.goto('/projects')
  await page.getByRole('button', { name: 'Новый проект' }).click()
  const dialog = page.getByRole('dialog', { name: 'Новый проект' })
  await dialog.getByRole('button', { name: 'Создать проект' }).click()
  await expect(dialog.getByText(/Назовите проект/)).toBeVisible()
  await dialog.getByRole('textbox', { name: 'Название' }).fill('Приёмка оборудования')
  await dialog.getByRole('button', { name: 'Создать проект' }).click()
  await expect(page).toHaveURL(/\/projects\//)
  await expect(page.getByText('С чего начнём')).toBeVisible()

  await page.getByRole('button', { name: /Вставить текст/ }).click()
  const text = page.getByRole('dialog', { name: 'Текстовый источник' })
  await text
    .getByRole('textbox', { name: 'Текст' })
    .fill('Мастер участка принимает оборудование, проверяет комплектность и подписывает акт.')
  await text.getByRole('button', { name: 'Добавить источник' }).click()
  await expect(page.getByText('Схемы пока нет')).toBeVisible()
  await expect(page.getByRole('button', { name: 'Анализ', exact: true })).toBeEnabled()
})

test('источник открывается с подсветкой цитаты из вопроса', async ({ page }) => {
  await page.goto(`/projects/${DEMO_PROJECT_ID}`)
  const quote = page.locator('[data-question="Q-4"]').getByRole('link').first()
  await quote.click()
  const sheet = page.getByRole('dialog')
  await expect(sheet.locator('mark[data-target="true"]')).toBeVisible()
  await expect(sheet.locator('mark[data-target="true"]')).toContainText('заявитель дополняет')
})

test('неизвестный адрес — 404, неизвестный проект — понятная ошибка', async ({ page }) => {
  await page.goto('/no-such-page')
  await expect(page.getByText('Такой страницы нет')).toBeVisible()
  await page.goto('/projects/00000000-0000-0000-0000-000000000000')
  await expect(page.getByText('Проект не найден')).toBeVisible()
})
