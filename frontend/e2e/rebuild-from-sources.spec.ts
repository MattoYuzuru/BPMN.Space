import { expect, test } from '@playwright/test'
import { createExampleProject, runViaApi } from './support'

test('явная пересборка: предупреждение, отмена без запроса и защита подтверждённой головы', async ({
  page,
  request,
}) => {
  const projectId = await createExampleProject(request)
  await runViaApi(request, projectId, 'build')
  const detail = await (await request.get(`/api/v1/projects/${projectId}`)).json()
  const requests: unknown[] = []
  // Не запускаем модель: этот сценарий проверяет контракт интерфейса и поведение при 409.
  await page.route(`**/api/v1/projects/${projectId}/runs`, async (route) => {
    requests.push(route.request().postDataJSON())
    await route.fulfill({
      status: 409,
      json: { detail: 'Схема уже изменена другим участником', code: 'stale_version' },
    })
  })
  await page.goto(`/projects/${projectId}`)
  const open = async () => {
    await page.getByRole('button', { name: 'Другие способы построения' }).click()
    await page.getByRole('menuitem', { name: 'Перестроить из источников' }).click()
  }
  await open()
  const dialog = page.getByRole('alertdialog', { name: 'Перестроить схему из источников?' })
  await expect(dialog).toContainText('Текущая схема останется в истории версий')
  await expect(dialog.getByRole('button', { name: 'Отмена' })).toBeFocused()
  await dialog.getByRole('button', { name: 'Отмена' }).click()
  await expect(dialog).toBeHidden()
  expect(requests).toEqual([])
  await open()
  await dialog.getByRole('button', { name: 'Перестроить', exact: true }).click()
  await expect(page.getByText('Схема уже изменена другим участником')).toBeVisible()
  await expect(dialog).toBeVisible()
  expect(requests).toEqual([
    { mode: 'build', replace_manual: true, base_version_id: detail.latest_version.id },
  ])
  await dialog.getByRole('button', { name: 'Отмена' }).click()
})
