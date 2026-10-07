import { expect, test } from '@playwright/test'
import { createExampleProject, runViaApi } from './support'

/** Быстрое ручное действие должно прервать движение камеры, сохранив редактирование подписи. */
test('двойной клик во время вписывания схемы сохраняет открытой правку подписи', async ({
  page,
  request,
}) => {
  await page.emulateMedia({ reducedMotion: 'no-preference' })
  const projectId = await createExampleProject(request)
  await runViaApi(request, projectId, 'build')
  await page.goto(`/projects/${projectId}`)
  await expect(page.locator('.djs-container')).toBeVisible()
  // Удлиняем только тестовый переход, чтобы гонка не зависела от скорости сборки и компьютера.
  await page.addStyleTag({ content: '.de-root { --duration-slow: 1200ms; }' })
  const task = page.locator('.djs-element[data-element-id="Task_SubmitApplication"]')
  const bounds = await task.boundingBox()
  if (!bounds) throw new Error('Задача должна быть видна на схеме')
  await page.getByRole('button', { name: 'Вписать в окно' }).click()
  // Нативные клики без ожидания стабильности locator: пользователь действует сразу после кнопки.
  await page.mouse.dblclick(bounds.x + bounds.width / 2, bounds.y + bounds.height / 2)
  const editor = page.locator('.djs-direct-editing-content')
  await expect(editor).toBeVisible()
  await page.evaluate(
    () =>
      new Promise<void>((resolve) =>
        requestAnimationFrame(() => requestAnimationFrame(() => resolve())),
      ),
  )
  await expect(editor).toBeVisible()
  await editor.fill('Уточнённое название задачи')
  await expect(editor).toHaveText('Уточнённое название задачи')
  await editor.press('Escape')
  await expect(editor).toBeHidden()
})
