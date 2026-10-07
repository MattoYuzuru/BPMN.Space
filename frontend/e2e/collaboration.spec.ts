import { readFileSync } from 'node:fs'
import { type Browser, expect, type Page, test } from '@playwright/test'
import { createExampleProject, runViaApi } from './support'

const SIGNED_OUT = { cookies: [], origins: [] }

/** Синхронизация сценария с комнатой не зависит от декоративного счётчика в интерфейсе. */
function observeRoom(page: Page): () => number {
  let sessions = new Set<string>()
  page.on('websocket', (socket) =>
    socket.on('framereceived', (frame) => {
      try {
        const event = JSON.parse(String(frame.payload)) as {
          type: string
          participants?: Array<{ session_id: string }>
          participant?: { session_id: string }
        }
        if (event.type === 'ready' || event.type === 'presence.snapshot') {
          sessions = new Set(event.participants?.map((item) => item.session_id))
        } else if (event.type === 'presence.changed' && event.participant) {
          sessions.add(event.participant.session_id)
        }
      } catch {
        // Прочие сообщения не определяют состав комнаты.
      }
    }),
  )
  return () => sessions.size
}

async function guestPage(browser: Browser, baseURL: string | undefined): Promise<Page> {
  const context = await browser.newContext({
    baseURL,
    locale: 'ru-RU',
    viewport: { width: 1440, height: 900 },
    storageState: SIGNED_OUT,
  })
  return context.newPage()
}

test('сохранение синхронизирует две вкладки одного аккаунта без перезагрузки', async ({
  page,
  request,
  browser,
  baseURL,
}) => {
  const projectId = await createExampleProject(request)
  const initialXml = readFileSync(
    new URL('../../examples/tp861/output/diagram-v2.bpmn', import.meta.url),
    'utf8',
  )
  const { csrf_token: csrf } = await (await request.get('/api/v1/auth/csrf')).json()
  const initial = await request.put(`/api/v1/projects/${projectId}/diagram`, {
    headers: { 'X-CSRF-Token': csrf },
    data: { xml: initialXml, base_version_id: null },
  })
  expect(initial.status()).toBe(201)
  const base = await initial.json()
  const otherContext = await browser.newContext({
    baseURL,
    storageState: await page.context().storageState(),
  })
  const other = await otherContext.newPage()
  const localCount = observeRoom(page)
  const remoteCount = observeRoom(other)
  try {
    await Promise.all([page.goto(`/projects/${projectId}`), other.goto(`/projects/${projectId}`)])
    await expect.poll(localCount, { timeout: 15_000 }).toBe(2)
    await expect.poll(remoteCount).toBe(2)
    const title = 'Заявка проверена во второй вкладке'
    const updatedXml = await page.evaluate(
      ({ xml, title }) => {
        const document = new DOMParser().parseFromString(xml, 'application/xml')
        const task = document.querySelector('[id="Task_SubmitApplication"]')
        if (!task) throw new Error('В исходной схеме нет задачи подачи заявки')
        task.setAttribute('name', title)
        return new XMLSerializer().serializeToString(document)
      },
      { xml: initialXml, title },
    )
    const saved = await request.put(`/api/v1/projects/${projectId}/diagram`, {
      headers: { 'X-CSRF-Token': csrf },
      data: { xml: updatedXml, base_version_id: base.id },
    })
    expect(saved.status()).toBe(201)
    for (const tab of [page, other]) {
      await expect(
        tab.locator('.djs-element[data-element-id="Task_SubmitApplication"]'),
      ).toContainText(title)
      await expect(tab.getByRole('button', { name: 'Открыть новую версию' })).toHaveCount(0)
    }
  } finally {
    await otherContext.close()
  }
})

test('движение BPMN-блока сразу видно во второй вкладке', async ({
  page,
  request,
  browser,
  baseURL,
}) => {
  const session = await (await request.get('/api/v1/auth/session')).json()
  test.skip(session.auth_enabled, 'Этот smoke-тест использует локальный режим без аккаунтов')

  const projectId = await createExampleProject(request)
  await runViaApi(request, projectId, 'build')
  const other = await guestPage(browser, baseURL)
  const localCount = observeRoom(page)
  const remoteCount = observeRoom(other)
  try {
    await Promise.all([page.goto(`/projects/${projectId}`), other.goto(`/projects/${projectId}`)])
    await expect.poll(localCount, { timeout: 15_000 }).toBe(2)
    await expect.poll(remoteCount).toBe(2)
    await page.getByRole('button', { name: 'Вписать в окно' }).click()
    await other.getByRole('button', { name: 'Вписать в окно' }).click()

    const local = page.locator('.djs-element[data-element-id="Task_SubmitApplication"]')
    const remote = other.locator('.djs-element[data-element-id="Task_SubmitApplication"]')
    const before = await remote.boundingBox()
    if (!before) throw new Error('Не удалось найти задачу во второй вкладке')
    const localBox = await local.boundingBox()
    if (!localBox) throw new Error('Не удалось найти задачу в первой вкладке')
    await page.mouse.move(localBox.x + localBox.width / 2, localBox.y + localBox.height / 2)
    await page.mouse.down()
    await page.mouse.move(
      localBox.x + localBox.width / 2 + 120,
      localBox.y + localBox.height / 2 + 50,
      { steps: 10 },
    )
    await expect
      .poll(async () => {
        const moved = await remote.boundingBox()
        return moved ? moved.x - before.x : 0
      })
      .toBeGreaterThan(50)
    await page.mouse.up()
  } finally {
    await other.context().close()
  }
})

test('общая доска показывает живое присутствие и курсор гостя viewer-ссылки', async ({
  page,
  request,
  browser,
  baseURL,
}) => {
  const session = await (await request.get('/api/v1/auth/session')).json()
  test.skip(!session.auth_enabled, 'Realtime-права проверяются на стенде с аккаунтами')

  const projectId = await createExampleProject(request)
  await runViaApi(request, projectId, 'build')
  const ownerCount = observeRoom(page)
  await page.goto(`/projects/${projectId}`)
  await page.getByRole('button', { name: 'Вписать в окно' }).click()
  await expect.poll(ownerCount, { timeout: 15_000 }).toBe(1)
  await expect(page.getByText(/\d+ в комнате/)).toHaveCount(0)

  await page.getByRole('button', { name: 'Поделиться' }).click()
  const dialog = page.getByRole('dialog', { name: 'Поделиться проектом' })
  await dialog.getByRole('radio', { name: 'Просмотр' }).click()
  await dialog.getByRole('button', { name: 'Создать ссылку' }).click()
  const shareUrl = await dialog.getByRole('textbox', { name: 'Ссылка' }).inputValue()
  expect(shareUrl).toMatch(/\/share\/[\w-]+$/)
  await page.keyboard.press('Escape')

  const guest = await guestPage(browser, baseURL)
  const guestCount = observeRoom(guest)
  const guestSelections: string[][] = []
  const guestDragFrames: Array<{ phase?: string; current?: { x: number; y: number } }> = []
  guest.on('websocket', (socket) =>
    socket.on('framereceived', (frame) => {
      try {
        const message = JSON.parse(String(frame.payload)) as {
          type?: string
          participant?: {
            selection?: string[]
            drag?: { phase?: string; current?: { x: number; y: number } } | null
          }
        }
        if (message.type === 'presence.changed' && message.participant?.selection) {
          guestSelections.push(message.participant.selection)
        }
        if (message.type === 'presence.changed' && message.participant?.drag) {
          guestDragFrames.push(message.participant.drag)
        }
      } catch {}
    }),
  )
  try {
    await guest.goto(shareUrl)
    await expect(guest.getByText('Только просмотр').first()).toBeVisible()
    await expect.poll(ownerCount, { timeout: 15_000 }).toBe(2)
    await expect.poll(guestCount).toBe(2)
    await expect(page.getByText(/\d+ в комнате/)).toHaveCount(0)

    const canvas = page.locator('[aria-label^="Схема процесса"] .djs-container')
    const bounds = await canvas.boundingBox()
    if (!bounds) throw new Error('Не удалось определить положение холста')
    await page.bringToFront()
    await page.mouse.move(bounds.x + bounds.width / 2, bounds.y + bounds.height / 2)

    await expect(guest.locator('[aria-hidden="true"] [data-icon="pointer"]')).toBeVisible({
      timeout: 5_000,
    })
    await page.locator('.djs-element[data-element-id="Task_SubmitApplication"]').click()
    await page.waitForTimeout(300)
    await expect
      .poll(() => guestSelections.some((ids) => ids.includes('Task_SubmitApplication')), {
        timeout: 5_000,
      })
      .toBe(true)
    await expect(guest.locator('.djs-element[class*="de-collab-selection-"]')).toHaveCount(1, {
      timeout: 5_000,
    })

    const task = page.locator('.djs-element[data-element-id="Task_SubmitApplication"]')
    const taskBefore = await task.boundingBox()
    if (!taskBefore) throw new Error('Не удалось определить положение BPMN-блока')
    await page.mouse.move(taskBefore.x + taskBefore.width / 2, taskBefore.y + taskBefore.height / 2)
    await page.mouse.down()
    await page.mouse.move(
      taskBefore.x + taskBefore.width / 2 + 100,
      taskBefore.y + taskBefore.height / 2 + 40,
      {
        steps: 8,
      },
    )
    await expect
      .poll(async () => {
        const moved = await guest
          .locator('.djs-element[data-element-id="Task_SubmitApplication"]')
          .boundingBox()
        return moved ? moved.x - taskBefore.x : 0
      })
      .toBeGreaterThan(40)
    await expect.poll(() => guestDragFrames.length).toBeGreaterThan(0)
    await page.mouse.up()
  } finally {
    await guest.context().close()
  }
})
