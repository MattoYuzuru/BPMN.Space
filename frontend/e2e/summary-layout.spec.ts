import { expect, test } from '@playwright/test'

test('итоги вопросов: равные ячейки и числа 0–999 остаются внутри узкой карточки', async ({
  page,
}) => {
  await page.goto('/styleguide')
  const summaries = page.locator('dl[aria-label="Итоги вопросов"]')
  await expect(summaries).toHaveCount(4)
  for (const width of [240, 280, 320, 440]) {
    for (const summary of await summaries.all()) {
      await summary.evaluate((element, value) => {
        element.setAttribute('style', `width: ${value}px`)
      }, width)
      const measurements = await summary.evaluate((element) => {
        const outer = element.getBoundingClientRect()
        const cells = Array.from(element.children).map((child) => child.getBoundingClientRect())
        const labels = Array.from(element.querySelectorAll('dt, dd')).map((child) =>
          child.getBoundingClientRect(),
        )
        return {
          widths: cells.map((box) => box.width),
          overflow: element.scrollWidth - element.clientWidth,
          outside: labels.some((box) => box.left < outer.left || box.right > outer.right),
        }
      })
      expect(measurements.overflow).toBe(0)
      expect(measurements.outside).toBe(false)
      expect(Math.max(...measurements.widths) - Math.min(...measurements.widths)).toBeLessThan(1)
    }
  }
})
