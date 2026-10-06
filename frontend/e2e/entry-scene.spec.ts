import { expect, test } from '@playwright/test'

test.use({ storageState: { cookies: [], origins: [] } })

for (const theme of ['light', 'dark'] as const) {
  test(`вход и приглашение: общая сетка и защищённая карточка, ${theme}`, async ({ page }) => {
    await page.addInitScript((value) => localStorage.setItem('arkhitektor.theme', value), theme)
    // Оба публичных экрана доступны гостю; приглашение не зависит от созданных ранее ссылок.
    await page.route('**/api/v1/auth/session', (route) =>
      route.fulfill({ json: { auth_enabled: true, user: null } }),
    )
    await page.route('**/api/v1/shares/entry-scene-test', (route) =>
      route.fulfill({ status: 401, json: { detail: 'Войдите в аккаунт' } }),
    )
    let loginClasses = ''
    for (const path of ['/login', '/share/entry-scene-test']) {
      await page.goto(path)
      await expect(page.locator('html')).toHaveAttribute('data-theme', theme)
      await expect(page.locator('main canvas')).toBeAttached()
      await expect(page.locator('main [data-lens-block]')).toBeVisible()
      const classes = await page.locator('main').getAttribute('class')
      if (path === '/login') loginClasses = classes ?? ''
      else expect(classes).toBe(loginClasses)
      const card = page.locator('main [data-lens-block]')
      const box = await card.boundingBox()
      expect(box?.width).toBeGreaterThan(300)
      expect(box?.width).toBeLessThanOrEqual(384)
      await page.mouse.move(200, 300)
      await page.emulateMedia({ reducedMotion: 'reduce' })
      await expect(page.locator('main .pattern-grid')).toBeVisible()
      await expect(page.locator('main .pattern-grid')).not.toHaveClass(/invisible/)
      await page.emulateMedia({ reducedMotion: 'no-preference' })
    }
  })
}
