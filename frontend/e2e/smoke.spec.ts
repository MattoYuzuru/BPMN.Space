import { expect, test } from '@playwright/test'

test('приложение открывается', async ({ page }) => {
  await page.goto('/')
  await expect(page).toHaveTitle(/Архитектор BPMN/)
  await expect(page.getByRole('heading', { name: /Из материалов/ })).toBeVisible()
})

test('backend отвечает через прокси', async ({ request }) => {
  const res = await request.get('/health')
  expect(await res.json()).toEqual({ status: 'ok' })
})
