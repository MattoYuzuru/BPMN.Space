import { expect, test } from '@playwright/test'

test('список проектов открывается на главной', async ({ page }) => {
  await page.goto('/')
  await expect(page).toHaveTitle(/Архитектор BPMN/)
  await expect(page.getByRole('heading', { name: 'Проекты' })).toBeVisible()
})

test('старый адрес рабочего места ведёт в единое пространство проекта', async ({ page }) => {
  const projectId = '00000000-0000-0000-0000-000000000000'
  await page.goto(`/studio/${projectId}`)
  await expect(page).toHaveURL(new RegExp(`/projects/${projectId}$`))
})

test('backend отвечает через прокси', async ({ request }) => {
  const res = await request.get('/health')
  expect(await res.json()).toEqual({ status: 'ok' })
})
