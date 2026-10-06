import { readFileSync } from 'node:fs'
import { expect, test } from '@playwright/test'
import { apiPost, createExampleProject, dragElement, runViaApi, startRun } from './support'

test('ручная правка → новый источник → обычная сборка → стандартный BPMN-экспорт', async ({
  page,
  request,
}) => {
  const projectId = await createExampleProject(request)
  await runViaApi(request, projectId, 'build')
  await page.goto(`/projects/${projectId}`)
  await expect(page.locator('.djs-container')).toBeVisible()
  await page.getByRole('button', { name: 'Вписать в окно' }).click()
  const element = page.locator('.djs-element[data-element-id="Task_SubmitApplication"]')
  await element.dblclick()
  const editor = page.locator('.djs-direct-editing-content')
  await expect(editor).toBeVisible()
  await editor.fill('Подать проверенную заявку')
  await page.getByRole('button', { name: 'Вписать в окно' }).click()
  await expect(page.getByText('Схема сохранена')).toBeVisible({ timeout: 15_000 })
  await dragElement(page, 'Task_SubmitApplication', 35, 0)

  const detail = async () => await (await request.get(`/api/v1/projects/${projectId}`)).json()
  await expect
    .poll(async () => (await detail()).latest_version.number, { timeout: 15_000 })
    .toBeGreaterThanOrEqual(3)
  const manual = (await detail()).latest_version
  expect(manual.trace.Task_SubmitApplication).toBeUndefined()
  const saved = await (await request.get(`/api/v1/versions/${manual.id}/xml`)).text()
  expect(saved).toContain('Подать проверенную заявку')

  const source = await apiPost(request, `/api/v1/projects/${projectId}/sources/text`, {
    title: 'Уточнение после ручной правки',
    content: 'Заявку нужно проверить до отправки. Ручное название уточняет этот этап.',
  })
  expect(source.ok()).toBeTruthy()
  await page.reload()
  const result = await startRun(page, 'build')
  await expect(result).toContainText('Схема построена')
  const generated = (await detail()).latest_version
  expect(generated.origin).toBe('generated')
  expect(generated.number).toBeGreaterThan(manual.number)
  const rebuilt = await (await request.get(`/api/v1/versions/${generated.id}/xml`)).text()
  expect(rebuilt).toContain('Подать проверенную заявку')
  expect(rebuilt).toContain('Gateway_Complete')
  expect(rebuilt).toContain('parallelGateway')
  const bounds = (xml: string) =>
    /<[^>]*BPMNShape\b[^>]*bpmnElement="Task_SubmitApplication"[^>]*>[\s\S]*?<[^>]*Bounds\b([^>]*)/u.exec(
      xml,
    )?.[1]
  expect(bounds(rebuilt)).toBe(bounds(saved))
  // Приоритет ручного смысла сохраняется и после того, как новая версия стала generated.
  await startRun(page, 'build')
  const repeated = (await detail()).latest_version
  expect(repeated.number).toBeGreaterThan(generated.number)
  const repeatedXml = await (await request.get(`/api/v1/versions/${repeated.id}/xml`)).text()
  expect(repeatedXml).toContain('Подать проверенную заявку')
  expect(bounds(repeatedXml)).toBe(bounds(saved))
  expect(repeated.trace.Task_SubmitApplication).toBeUndefined()
  const history = await (await request.get(`/api/v1/projects/${projectId}/versions`)).json()
  expect(history.some((version: { id: string }) => version.id === manual.id)).toBe(true)

  await page.getByRole('button', { name: 'Скачать схему' }).click()
  const download = page.waitForEvent('download')
  await page.getByRole('menuitem', { name: /\.bpmn/ }).click()
  const file = await download
  const exported = readFileSync(await file.path(), 'utf8')
  expect(exported).toContain('Подать проверенную заявку')
  expect(exported).toContain('http://www.omg.org/spec/BPMN/20100524/MODEL')
  expect(exported).not.toContain('schema_version')
})
