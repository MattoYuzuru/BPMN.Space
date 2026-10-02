import { mkdirSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { expect, type Locator, type Page, test } from '@playwright/test'
import { createExampleProject, DEMO_PROJECT_ID, questionCard } from './support'

/**
 * Набор скриншотов ключевых экранов для команды и жюри: `make screenshots` → reports/screenshots.
 * Снимается на свежем mock-бэкенде (демо-проект «Технологическое присоединение» в исходном
 * состоянии), окно 1600×1000, плотность 2×. Кадры идут по порядку: анализ демо-проекта меняет
 * его состояние, поэтому он снимается последним.
 */
const OUT = fileURLToPath(new URL('../../reports/screenshots/', import.meta.url))
mkdirSync(OUT, { recursive: true })

test.describe.configure({ mode: 'serial' })

type Theme = 'light' | 'dark'

async function open(page: Page, path: string, theme: Theme = 'light') {
  await page.addInitScript((value) => {
    localStorage.setItem('arkhitektor.theme', value)
  }, theme)
  await page.goto(path)
}

/** Уведомления живут 5 с и закрывают углы кадра — прячем, где они не главное. */
async function hideToasts(page: Page) {
  await page.addStyleTag({ content: '[data-sonner-toaster]{display:none!important}' })
}

/** Дождаться конца переходов: шрифты, анимации появления, плавный масштаб схемы. */
async function settle(page: Page, ms = 700) {
  await page.evaluate('document.fonts.ready')
  await page.waitForTimeout(ms)
}

async function shoot(page: Page, name: string, target?: Locator) {
  const path = `${OUT}${name}.png`
  if (target) await target.screenshot({ path, animations: 'disabled' })
  else await page.screenshot({ path })
}

async function openDemo(page: Page, theme: Theme = 'light') {
  await open(page, `/projects/${DEMO_PROJECT_ID}`, theme)
  await expect(page.locator('.djs-container')).toBeVisible()
  await expect(page.locator('.hl-assumption').first()).toBeAttached()
}

test('01–02 список проектов', async ({ page }) => {
  await open(page, '/projects')
  await expect(page.getByRole('link', { name: /электросетям/ })).toBeVisible()
  await settle(page, 900)
  await shoot(page, '01-projects-light')

  await page.getByRole('radio', { name: 'Тёмная' }).click()
  await page.mouse.move(800, 990)
  await settle(page, 900)
  await shoot(page, '02-projects-dark')
})

test('03 создание проекта', async ({ page }) => {
  await open(page, '/projects')
  await page.getByRole('button', { name: 'Начать с примера' }).first().click()
  const dialog = page.getByRole('dialog', { name: 'Новый проект' })
  await expect(dialog.getByRole('radio', { name: /Технологическое/ })).toBeChecked()
  await dialog.getByRole('radio', { name: /Вывод оборудования/ }).click()
  await settle(page)
  await shoot(page, '03-create-project')
})

test('04–07 рабочее место, карточки вопросов, схема с маркерами', async ({ page }) => {
  await openDemo(page, 'light')
  await hideToasts(page)
  // Выбранный вопрос: свечение карточки и подсветка его элементов на схеме.
  await questionCard(page, 'Q-3').getByText('Кто выставляет счёт').click()
  await settle(page, 1200)
  await shoot(page, '04-workspace-light')

  await shoot(page, '06-question-cards', page.getByRole('region', { name: 'Вопросы' }))

  await page.getByRole('button', { name: 'Увеличить' }).click()
  await settle(page, 600)
  await shoot(page, '07-diagram-markers', page.getByRole('region', { name: 'Схема', exact: true }))

  await openDemo(page, 'dark')
  await hideToasts(page)
  await questionCard(page, 'Q-4').getByText('Что происходит').click()
  await settle(page, 1200)
  await shoot(page, '05-workspace-dark')
})

test('11 источник с подсветкой цитаты', async ({ page }) => {
  await openDemo(page)
  await hideToasts(page)
  await questionCard(page, 'Q-6').getByRole('link').first().click()
  const sheet = page.getByRole('dialog')
  await expect(sheet.locator('mark[data-target="true"]')).toBeVisible()
  await settle(page, 900)
  await shoot(page, '11-source-quote')
})

test('12–13 отчёт проверки и версии', async ({ page }) => {
  await openDemo(page)
  await hideToasts(page)
  await page.getByRole('button', { name: 'Проверка' }).click()
  await expect(page.getByRole('dialog', { name: 'Проверка схемы' })).toBeVisible()
  await settle(page, 900)
  await shoot(page, '12-report')
  // Закрываем мышью: после Esc браузер показал бы кольцо фокуса в следующем окне.
  await page
    .getByRole('dialog', { name: 'Проверка схемы' })
    .getByRole('button', { name: 'Закрыть' })
    .click()

  await page.getByRole('button', { name: /^Версия/ }).click()
  await page.getByRole('menuitem', { name: 'Вся история' }).click()
  await expect(page.getByRole('dialog', { name: 'Версии схемы' })).toBeVisible()
  await settle(page, 900)
  await shoot(page, '13-versions')
})

test('14 палитра команд', async ({ page }) => {
  await openDemo(page)
  await hideToasts(page)
  await page.keyboard.press('Control+k')
  await expect(page.getByRole('dialog', { name: 'Палитра команд' })).toBeVisible()
  await page.getByRole('combobox').fill('схем')
  await settle(page, 600)
  await shoot(page, '14-command-palette')
})

test('15 симуляция токена', async ({ page }) => {
  await openDemo(page)
  await hideToasts(page)
  await page.getByRole('button', { name: 'Симуляция токена' }).click()
  const trigger = page.locator(
    '.djs-overlays[data-container-id="StartEvent_Need"] .bts-context-pad',
  )
  // Кнопки симуляции bpmn-js показывает только при достаточном масштабе — жмём напрямую.
  await trigger.first().dispatchEvent('click')
  for (let step = 0; step < 3; step += 1) {
    await page.getByRole('button', { name: 'Увеличить' }).click()
  }
  await page.mouse.move(10, 990)
  await page.waitForTimeout(3800)
  await shoot(page, '15-token-simulation', page.getByRole('region', { name: 'Схема', exact: true }))
})

test('16 стайлгайд', async ({ page }) => {
  await open(page, '/styleguide')
  await expect(page.getByRole('heading', { name: 'Дизайн-система Архитектора' })).toBeVisible()
  await settle(page, 900)
  await shoot(page, '16-styleguide')
})

test('10 запись голоса', async ({ page, request }) => {
  const projectId = await createExampleProject(request)
  await open(page, `/projects/${projectId}`)
  await hideToasts(page)
  await page.getByRole('button', { name: 'Добавить источник' }).click()
  await page.getByRole('menuitem', { name: 'Голосовая заметка' }).click()
  const dialog = page.getByRole('dialog', { name: 'Голосовая заметка' })
  await expect(dialog.getByText('Идёт запись')).toBeVisible()
  await page.waitForTimeout(3200)
  await shoot(page, '10-voice-recording')
  await dialog.getByRole('button', { name: 'Отменить' }).click()
})

test('08–09 ход и итог анализа демо-проекта', async ({ page }) => {
  await openDemo(page)
  await hideToasts(page)
  await page.getByRole('button', { name: 'Анализ', exact: true }).click()
  const card = page.getByRole('status', { name: /Ход прогона/ })
  // Середина анализа: модель ищет участников и шаги (≈2,4 с при MOCK_DELAY_SCALE=1).
  await expect(card.locator('li[aria-current="step"]')).toContainText('Ищу участников', {
    timeout: 15_000,
  })
  await page.waitForTimeout(500)
  await shoot(page, '08-run-progress')

  await expect(card).toContainText('Анализ завершён', { timeout: 30_000 })
  await page.addStyleTag({ content: '[data-sonner-toaster]{display:block!important}' })
  await settle(page, 1200)
  await shoot(page, '09-run-summary')
})
