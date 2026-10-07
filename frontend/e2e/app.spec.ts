import { expect, test } from '@playwright/test'
import { createExampleProject, DEMO_PROJECT_ID, runViaApi } from './support'

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

test('новый проект с описанием сразу запускает сборку схемы', async ({ page }) => {
  await page.goto('/projects')
  await page.getByRole('button', { name: 'Новый проект' }).click()
  const dialog = page.getByRole('dialog', { name: 'Новый проект' })
  await dialog.getByRole('textbox', { name: 'Название' }).fill('Согласование договора')
  await dialog
    .getByRole('textbox', { name: 'Описание процесса' })
    .fill(
      'Юрист проверяет договор. Если есть замечания, он возвращает договор автору. Затем директор подписывает.',
    )
  await dialog.getByRole('button', { name: 'Создать проект' }).click()

  await expect(page).toHaveURL(/\/projects\/[0-9a-f-]+$/)
  await expect(page.getByRole('status', { name: /Ход прогона/ })).toBeVisible()
  await expect(page.getByText('Описание процесса').first()).toBeVisible()
})

test('описание процесса можно надиктовать голосом', async ({ page }) => {
  await page.goto('/projects')
  await page.getByRole('button', { name: 'Новый проект' }).click()
  const dialog = page.getByRole('dialog', { name: 'Новый проект' })
  await dialog.getByRole('button', { name: 'Надиктовать' }).click()
  await expect(page.getByText('Идёт запись')).toBeVisible()
  await expect(dialog.getByRole('textbox', { name: 'Описание процесса' })).toBeHidden()
  await expect(page.getByRole('dialog')).toHaveCount(1)
  await page.waitForTimeout(1200)
  await page.getByRole('button', { name: 'Остановить и вставить текст' }).click()
  await expect(dialog.getByRole('textbox', { name: 'Описание процесса' })).not.toHaveValue('')
  await expect(dialog.getByRole('textbox', { name: 'Описание процесса' })).toBeFocused()
})

test('тишина в диктовке сохраняет черновик и показывает уведомление', async ({ page }) => {
  await page.route('**/api/v1/transcriptions', (route) =>
    route.fulfill({
      status: 422,
      contentType: 'application/json',
      body: JSON.stringify({
        detail: 'Не удалось распознать речь. Попробуйте записать ещё раз.',
        code: 'NO_SPEECH',
      }),
    }),
  )
  await page.goto('/projects')
  await page.getByRole('button', { name: 'Новый проект' }).click()
  const dialog = page.getByRole('dialog', { name: 'Новый проект' })
  const description = dialog.getByRole('textbox', { name: 'Описание процесса' })
  await description.fill('Текст до записи')
  await dialog.getByRole('button', { name: 'Надиктовать' }).click()
  await expect(dialog.getByText('Идёт запись')).toBeVisible()
  await dialog.getByRole('button', { name: 'Остановить и вставить текст' }).click()
  await expect(page.getByText('Речь не распознана', { exact: true })).toBeVisible()
  await expect(description).toHaveValue('Текст до записи')
  await expect(description).toBeFocused()
  await expect(page.getByText(/Ошибка сервера/)).toBeHidden()
})

test('главная сетка сохраняет три крупные карточки на широком окне', async ({ page }) => {
  await page.setViewportSize({ width: 1920, height: 1080 })
  await page.goto('/projects')
  const grid = page.locator('[data-projects-grid]')
  await expect(grid).toBeVisible()
  const columns = await grid.evaluate((element) => getComputedStyle(element).gridTemplateColumns)
  expect(columns.split(' ')).toHaveLength(3)
})

test('голосовой ответ можно проверить после остановки или отправить сразу', async ({
  page,
  request,
}) => {
  await page.emulateMedia({ reducedMotion: 'reduce' })
  await page.route('**/api/v1/transcriptions', (route) =>
    route.fulfill({
      contentType: 'application/json',
      body: JSON.stringify({
        text: 'Проверку выполняет оператор.',
        duration_sec: 2,
        language: 'ru',
      }),
    }),
  )
  const projectId = await createExampleProject(request)
  await runViaApi(request, projectId, 'analyze')
  await page.goto(`/projects/${projectId}`)
  const card = page.locator('[data-question="Q-1"]')
  await card.getByRole('button', { name: 'Ответить', exact: true }).click()
  const field = card.getByRole('textbox')
  await field.fill('Черновик ответа.')
  await card.getByRole('button', { name: 'Ответить голосом' }).click()
  await expect(card.getByText('Идёт запись')).toBeVisible()
  await expect(page.getByRole('dialog')).toHaveCount(0)
  await expect(card.getByText('0:01', { exact: true })).toBeVisible()
  const voice = card.getByRole('group', { name: 'Ввод текста или запись голоса' })
  expect(await voice.evaluate((element) => element.scrollWidth <= element.clientWidth)).toBe(true)
  await card.screenshot({ path: '../reports/screenshots/quality-voice-inline-light.png' })
  await page.getByRole('radio', { name: 'Тёмная', exact: true }).click()
  await card.screenshot({ path: '../reports/screenshots/quality-voice-inline-dark.png' })
  await page.getByRole('radio', { name: 'Светлая', exact: true }).click()
  await card.getByRole('button', { name: 'Остановить и вставить текст' }).click()
  await expect(field).toHaveValue('Черновик ответа.\nПроверку выполняет оператор.')
  await expect(card.getByRole('button', { name: 'Отправить ответ' })).toBeEnabled()
  await card.getByRole('button', { name: 'Ответить голосом' }).click()
  await expect(card.getByText('Идёт запись')).toBeVisible()
  await card.getByRole('button', { name: 'Распознать и отправить ответ' }).click()
  await expect(card).toBeHidden()
  await page.getByRole('tab', { name: /Решённые/ }).click()
  await expect(card).toContainText('Черновик ответа.')
  await expect(card).toContainText('Проверку выполняет оператор.')
})

test('диалог создания проекта показывает форму целиком', async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 800 })
  await page.goto('/projects')
  await page.getByRole('button', { name: 'Новый проект' }).click()

  const dialog = page.getByRole('dialog', { name: 'Новый проект' })
  await expect(dialog.getByRole('textbox', { name: 'Название' })).toBeInViewport()
  await expect(dialog.getByRole('textbox', { name: 'Описание' })).toBeInViewport()
  await expect(dialog.getByRole('button', { name: 'Создать проект' })).toBeInViewport()

  const bounds = await dialog.boundingBox()
  expect(bounds?.height).toBeGreaterThan(300)
  expect(bounds?.height).toBeLessThan(800)
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
