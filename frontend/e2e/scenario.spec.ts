import { readFileSync } from 'node:fs'
import { expect, test } from '@playwright/test'
import { DEMO_PROJECT_TITLE, dragElement, FINANCES_MD, questionCard, startRun } from './support'

/**
 * Ключевой сценарий RFC §2.1 целиком, как его проходит аналитик: список → проект из примера →
 * анализ → ответ, игнор, голос, документ → повторный анализ (решено/новые) → схема с маркерами →
 * правка мышью → новая версия manual → скачивание .bpmn.
 */
test('список проектов: пять учебных примеров и поиск демо-проекта', async ({ page }) => {
  await page.goto('/projects')
  await expect(page).toHaveTitle(/Проекты/)
  await page.getByRole('radio', { name: 'Примеры', exact: true }).click()
  await expect(page).toHaveURL(/scope=examples/)
  const cards = page.locator('section[aria-label="Проекты"] a[href^="/projects/"]')
  await expect(cards.first()).toBeVisible()
  await expect(cards).toHaveCount(5)

  await page.mouse.wheel(0, -100_000)
  await page.getByRole('searchbox', { name: 'Поиск по проектам' }).fill('электросетям')
  await expect(page).toHaveURL(/q=/)
  const demo = page.getByRole('link', { name: DEMO_PROJECT_TITLE })
  await expect(demo).toBeVisible()
  await demo.click()
  await expect(page.getByRole('region', { name: 'Вопросы' })).toBeVisible()
  await expect(page.locator('.djs-container')).toBeVisible()
  await expect(page.locator('.hl-assumption').first()).toBeAttached()
})

test('полный сценарий: вопросы, голос, документ, схема, правка, скачивание', async ({ page }) => {
  test.slow()

  await test.step('создать проект из примера', async () => {
    await page.goto('/projects')
    await page.getByRole('button', { name: 'Начать с примера' }).first().click()
    const dialog = page.getByRole('dialog', { name: 'Новый проект' })
    await expect(dialog.getByRole('radio', { name: /Технологическое присоединение/ })).toBeChecked()
    await dialog.getByRole('button', { name: 'Начать с примера' }).click()
    await expect(page).toHaveURL(/\/projects\//)
    await expect(page.getByText('Схемы пока нет')).toBeVisible()
  })

  await test.step('анализ: SSE до конца, вопросы появились', async () => {
    await startRun(page, 'analyze')
    await expect(questionCard(page, 'Q-1')).toBeVisible()
    await expect(page.getByRole('tab', { name: /Открытые/ })).toContainText('4')
  })

  await test.step('ответ текстом', async () => {
    const card = questionCard(page, 'Q-1')
    await card.getByRole('button', { name: 'Ответить', exact: true }).click()
    await card
      .getByRole('textbox')
      .fill('Уведомление направляет сетевая организация через личный кабинет заявителя.')
    await card.getByRole('button', { name: 'Отправить ответ' }).click()
    await expect(card).toBeHidden()
    await expect(page.getByRole('tab', { name: /Открытые/ })).toContainText('3')
    await page.getByRole('tab', { name: /Решённые/ }).click()
    await expect(card.getByText('Ваш ответ')).toBeVisible()
    await expect(card.getByText('Ответ учтётся при следующем анализе')).toBeVisible()
    await expect(card.getByText('Ответ получен', { exact: true })).toBeVisible()
    await card.getByRole('button', { name: 'Вернуть', exact: true }).click()
    await expect(card).toBeHidden()
    await expect(page.getByRole('tab', { name: /Открытые/ })).toContainText('4')
    await page.getByRole('tab', { name: /Открытые/ }).click()
    await expect(card.getByText('Ваш ответ')).toHaveCount(0)
    await card.getByRole('button', { name: 'Ответить', exact: true }).click()
    await card
      .getByRole('textbox')
      .fill('Уведомление направляет сетевая организация через личный кабинет заявителя.')
    await card.getByRole('button', { name: 'Отправить ответ' }).click()
    await expect(page.getByRole('tab', { name: /Открытые/ })).toContainText('3')
    await page.getByRole('tab', { name: /Открытые/ }).click()
  })

  await test.step('игнорировать вопрос — уходит в допущения', async () => {
    await questionCard(page, 'Q-2').getByRole('button', { name: 'Игнорировать' }).click()
    await expect(page.getByRole('tab', { name: /Допущения/ })).toContainText('1')
    await page.getByRole('tab', { name: /Допущения/ }).click()
    await expect(questionCard(page, 'Q-2').getByText('Принято допущение')).toBeVisible()
    await page.getByRole('tab', { name: /Открытые/ }).click()
  })

  await test.step('голосовая заметка как источник', async () => {
    await page.getByRole('button', { name: 'Добавить источник' }).click()
    await page.getByRole('menuitem', { name: 'Голосовая заметка', exact: true }).click()
    const dialog = page.getByRole('dialog', { name: 'Голосовая заметка' })
    await expect(dialog.getByText('Идёт запись')).toBeVisible()
    await expect(dialog.getByRole('meter', { name: 'Уровень сигнала микрофона' })).toBeVisible()
    await page.waitForTimeout(1200)
    await dialog.getByRole('button', { name: 'Остановить' }).click()
    const transcript = dialog.getByRole('textbox', { name: 'Расшифровка' })
    await expect(transcript).not.toBeEmpty({ timeout: 15_000 })
    await dialog.getByRole('button', { name: 'Добавить как источник' }).click()
    await expect(dialog).toBeHidden()
    await expect(
      page
        .getByRole('region', { name: 'Источники' })
        .getByText(/Голосовая заметка/)
        .first(),
    ).toBeVisible()
  })

  await test.step('документ .md', async () => {
    const chooser = page.waitForEvent('filechooser')
    await page
      .getByRole('region', { name: 'Источники' })
      .getByRole('button', { name: 'Выбрать файл' })
      .click()
    await (await chooser).setFiles(FINANCES_MD)
    await expect(
      page
        .getByRole('region', { name: 'Источники' })
        .getByRole('link', { name: /project-finances\.md/ }),
    ).toBeVisible()
  })

  await test.step('повторный анализ: вопрос решён, новый появился', async () => {
    const run = await startRun(page, 'analyze')
    await expect(run).not.toContainText(/Решено\s*0/)
    await expect(questionCard(page, 'Q-5')).toBeVisible()
    await page.getByRole('tab', { name: /Решённые/ }).click()
    await expect(questionCard(page, 'Q-3')).toContainText('project-finances.md')
    await page.getByRole('tab', { name: /Открытые/ }).click()
  })

  await test.step('построить схему: маркеры допущений и выбранного вопроса', async () => {
    await startRun(page, 'build')
    await expect(page.locator('.djs-container')).toBeVisible()
    await expect(page.locator('[data-element-id="Task_OfferSmall"]').first()).toBeAttached()
    await expect(page.locator('.hl-assumption').first()).toBeAttached()
    await questionCard(page, 'Q-4').getByRole('button', { name: 'Показать на схеме' }).click()
    await expect(page.locator('.hl-selected').first()).toBeAttached()
  })

  await test.step('правка схемы мышью → новая версия manual', async () => {
    await page.getByRole('button', { name: 'Скрыть' }).click()
    await page.getByRole('button', { name: 'Вписать в окно' }).click()
    await page.waitForTimeout(600)
    await dragElement(page, 'Task_Inspection', 40, 30)
    await expect(page.getByText('Схема сохранена')).toBeVisible({ timeout: 15_000 })
    await expect(page.getByRole('button', { name: /^Версия 2/ })).toBeVisible()
    await expect(page.getByRole('button', { name: /Правка вручную/ })).toBeVisible()
  })

  await test.step('скачать .bpmn', async () => {
    await page.getByRole('button', { name: 'Скачать схему' }).click()
    const download = page.waitForEvent('download')
    await page.getByRole('menuitem', { name: /\.bpmn/ }).click()
    const file = await download
    expect(file.suggestedFilename()).toMatch(/2\.bpmn$/)
    const xml = readFileSync(await file.path(), 'utf8')
    expect(xml).toContain('bpmn:definitions')
    expect(xml).toContain('Task_Inspection')
  })
})
