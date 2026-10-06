import { expect, type Page, test } from '@playwright/test'
import { createExampleProject } from './support'

/** Настоящий интерфейс и EventSource; записанный прогон без модели/искусственных backend-пауз. */
async function recordedRun(
  page: Page,
  projectId: string,
  status: 'succeeded' | 'failed' | 'cancelled',
  delay = 0,
) {
  let sequence = 0
  await page.route(`**/api/v1/projects/${projectId}/runs`, async (route) => {
    const started = Date.now()
    const id = `recorded-progress-${++sequence}`
    const run = {
      id,
      project_id: projectId,
      mode: 'analyze',
      status: 'queued',
      stage: null,
      progress: 0,
      stage_label: 'В очереди',
      started_at: new Date(started).toISOString(),
    }
    await page.route(`**/api/v1/runs/${id}/events`, async (events) => {
      const stage = (number: number, name: string) =>
        `id: ${number}\nevent: stage\ndata: ${JSON.stringify({ stage: name, label: name, progress: number / 4 })}\n\n`
      const stages =
        status === 'succeeded'
          ? stage(1, 'reading_sources') + stage(2, 'extracting') + stage(3, 'reconciling')
          : stage(1, 'reading_sources')
      if (delay) await new Promise((resolve) => setTimeout(resolve, delay))
      const done = {
        ...run,
        status,
        finished_at: new Date(started + delay + 100).toISOString(),
        summary: { resolved: 0, open: 2, new: 2, ignored: 0, answered: 0 },
        error: status === 'failed' ? 'Модель недоступна' : null,
      }
      await events.fulfill({
        contentType: 'text/event-stream',
        body: `${stages}id: 10\nevent: done\ndata: ${JSON.stringify({ run: done })}\n\n`,
      })
    })
    await route.fulfill({ status: 202, json: run })
  })
}

test('быстрый анализ завершает этапы, итог виден 2,5 с; повторный запуск имеет свою очередь', async ({
  page,
  request,
}) => {
  const projectId = await createExampleProject(request)
  await recordedRun(page, projectId, 'succeeded')
  await page.goto(`/projects/${projectId}`)
  const card = page.getByRole('status', { name: /Ход прогона/ })
  for (let round = 0; round < 2; round++) {
    await page.getByRole('button', { name: 'Анализ', exact: true }).click()
    await expect(card.getByRole('list', { name: 'Этапы прогона' })).toBeVisible()
    await expect(card).toContainText('Анализ завершён')
    const shown = Date.now()
    await expect(card).toBeHidden({ timeout: 4000 })
    expect(Date.now() - shown).toBeGreaterThanOrEqual(2200)
  }
})

for (const status of ['failed', 'cancelled'] as const) {
  test(`прогон ${status}: немедленный результат остаётся доступен`, async ({ page, request }) => {
    const projectId = await createExampleProject(request)
    await recordedRun(page, projectId, status)
    await page.goto(`/projects/${projectId}`)
    await page.getByRole('button', { name: 'Анализ', exact: true }).click()
    const card = page.getByRole('status', { name: /Ход прогона/ })
    await expect(card).toContainText(status === 'failed' ? 'Прогон остановлен' : 'Прогон отменён')
    await expect(card).not.toContainText('Анализ завершён')
    await page.clock.install()
    await page.clock.fastForward(5000)
    await expect(card).toBeVisible()
    await card.getByRole('button', { name: 'Скрыть' }).click()
    await expect(card).toBeHidden()
  })
}

test('долгий прогон остаётся в работе; reduced motion не сокращает чтение итога', async ({
  page,
  request,
}) => {
  await page.emulateMedia({ reducedMotion: 'reduce' })
  const projectId = await createExampleProject(request)
  await recordedRun(page, projectId, 'succeeded', 1200)
  await page.goto(`/projects/${projectId}`)
  await page.getByRole('button', { name: 'Анализ', exact: true }).click()
  const card = page.getByRole('status', { name: /Ход прогона/ })
  await expect(card.getByRole('list', { name: 'Этапы прогона' })).toBeVisible()
  await expect(card).toContainText('Анализ завершён')
  const shown = Date.now()
  await expect(card).toBeHidden({ timeout: 4000 })
  expect(Date.now() - shown).toBeGreaterThanOrEqual(2200)
})
