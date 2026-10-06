/// <reference lib="dom" />
import { mkdirSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { expect, type Page, test } from '@playwright/test'
import type { DiagramEditorHandle } from '../src/widgets/diagram-editor/types'

/** Доступно только на dev-маршруте после ожидания open(). */
declare const window: Window & {
  __diagram: DiagramEditorHandle
  __diagramSetXml: (xml: string) => void
  __diagramEvents: Array<{ type: string }>
}

const OUT = fileURLToPath(new URL('../../reports/tmp/playback-review/', import.meta.url))
mkdirSync(OUT, { recursive: true })

interface Node {
  id: string
  type: string
  x: number
  y: number
  name?: string
  event?: string
}
interface Flow {
  id: string
  from: string
  to: string
  name?: string
}

/** Маленькие BPMN-фикстуры с настоящим DI: тест не заменяет Simulator/canvas моками. */
function xml(nodes: Node[], flows: Flow[]) {
  const shape = (node: Node) =>
    node.type.includes('Event') || node.type.includes('Gateway') ? 36 : 80
  return `<?xml version="1.0" encoding="UTF-8"?>
  <bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL" xmlns:bpmndi="http://www.omg.org/spec/BPMN/20100524/DI" xmlns:dc="http://www.omg.org/spec/DD/20100524/DC" xmlns:di="http://www.omg.org/spec/DD/20100524/DI" id="Definitions" targetNamespace="http://example.test/bpmn">
    <bpmn:process id="Process" name="Проверка процесса" isExecutable="false">
    ${nodes
      .map(
        (n) =>
          `<bpmn:${n.type} id="${n.id}" name="${n.name || n.id}">${flows
            .filter((f) => f.to === n.id)
            .map((f) => `<bpmn:incoming>${f.id}</bpmn:incoming>`)
            .join('')}${flows
            .filter((f) => f.from === n.id)
            .map((f) => `<bpmn:outgoing>${f.id}</bpmn:outgoing>`)
            .join(
              '',
            )}${n.event ? `<bpmn:${n.event} id="${n.id}_definition"/>` : ''}</bpmn:${n.type}>`,
      )
      .join('')}
    ${flows.map((f) => `<bpmn:sequenceFlow id="${f.id}" sourceRef="${f.from}" targetRef="${f.to}" name="${f.name || f.id}"/>`).join('')}
    </bpmn:process><bpmndi:BPMNDiagram id="Diagram"><bpmndi:BPMNPlane id="Plane" bpmnElement="Process">
    ${nodes.map((n) => `<bpmndi:BPMNShape id="${n.id}_di" bpmnElement="${n.id}"><dc:Bounds x="${n.x}" y="${n.y}" width="${shape(n)}" height="${shape(n)}"/></bpmndi:BPMNShape>`).join('')}
    ${flows
      .map((f) => {
        const a = nodes.find((n) => n.id === f.from)
        const b = nodes.find((n) => n.id === f.to)
        if (!a || !b) throw new Error(`Поток ${f.id} ссылается на отсутствующий узел`)
        return `<bpmndi:BPMNEdge id="${f.id}_di" bpmnElement="${f.id}"><di:waypoint x="${a.x + shape(a)}" y="${a.y + shape(a) / 2}"/><di:waypoint x="${b.x}" y="${b.y + shape(b) / 2}"/></bpmndi:BPMNEdge>`
      })
      .join('')}
    </bpmndi:BPMNPlane></bpmndi:BPMNDiagram></bpmn:definitions>`
}
const linear = xml(
  [
    { id: 'Start', type: 'startEvent', x: 100, y: 180 },
    { id: 'Task', type: 'task', x: 300, y: 158 },
    { id: 'End', type: 'endEvent', x: 600, y: 180 },
  ],
  [
    { id: 'F1', from: 'Start', to: 'Task' },
    { id: 'F2', from: 'Task', to: 'End' },
  ],
)
const parallel = xml(
  [
    { id: 'Start', type: 'startEvent', x: 100, y: 180 },
    { id: 'Fork', type: 'parallelGateway', x: 250, y: 180 },
    { id: 'A', type: 'task', x: 400, y: 70 },
    {
      id: 'Timer',
      name: 'Ожидание подтверждения',
      type: 'intermediateCatchEvent',
      event: 'timerEventDefinition',
      x: 400,
      y: 300,
    },
    { id: 'Join', type: 'parallelGateway', x: 650, y: 180 },
    { id: 'End', type: 'endEvent', x: 900, y: 180 },
  ],
  [
    { id: 'F1', from: 'Start', to: 'Fork' },
    { id: 'FA', from: 'Fork', to: 'A' },
    { id: 'FB', from: 'Fork', to: 'Timer' },
    { id: 'FAJ', from: 'A', to: 'Join' },
    { id: 'FBJ', from: 'Timer', to: 'Join' },
    { id: 'FE', from: 'Join', to: 'End' },
  ],
)
const loop = xml(
  [
    { id: 'Start', type: 'startEvent', x: 100, y: 180 },
    { id: 'Xor', name: 'Продолжить цикл?', type: 'exclusiveGateway', x: 300, y: 180 },
    { id: 'Task', type: 'task', x: 450, y: 70 },
    { id: 'End', type: 'endEvent', x: 650, y: 180 },
  ],
  [
    { id: 'F1', from: 'Start', to: 'Xor' },
    { id: 'Again', name: 'Ещё раз', from: 'Xor', to: 'Task' },
    { id: 'Back', from: 'Task', to: 'Xor' },
    { id: 'Done', name: 'Закончить', from: 'Xor', to: 'End' },
  ],
)
const multiple = xml(
  [
    { id: 'StartA', name: 'Заявка', type: 'startEvent', x: 100, y: 80 },
    { id: 'StartB', name: 'Уведомление', type: 'startEvent', x: 100, y: 280 },
    { id: 'End', type: 'endEvent', x: 650, y: 180 },
  ],
  [
    { id: 'FA', from: 'StartA', to: 'End' },
    { id: 'FB', from: 'StartB', to: 'End' },
  ],
)

async function open(page: Page, source = linear, readOnly = false) {
  const errors: string[] = []
  page.on('pageerror', (error) => errors.push(error.message))
  await page.goto(`/dev/diagram${readOnly ? '?readOnly=1' : ''}`)
  await page.waitForFunction(() => window.__diagram && window.__diagramSetXml)
  await page.evaluate((source) => window.__diagramSetXml?.(source), source)
  await expect(
    page.locator('.djs-shape[data-element-id="Start"], .djs-shape[data-element-id="StartA"]'),
  ).toHaveCount(1)
  await page.waitForFunction(
    () => window.__diagramEvents?.filter((e) => e.type === 'import').length === 2,
  )
  await page.evaluate(() => window.__diagram.fit())
  await page.waitForTimeout(350)
  return errors
}
const panel = (page: Page) => page.getByRole('group', { name: 'Воспроизведение процесса' })
const start = (page: Page) => page.evaluate(() => window.__diagram?.toggleSimulation(true))

test('видимый токен, пауза, завершение, повтор и чистый экспорт', async ({ page }) => {
  const errors = await open(page)
  const baseline = await page.evaluate(() => window.__diagram.exportXml())
  await start(page)
  await expect(panel(page)).toContainText('Процесс воспроизводится')
  await expect(page.locator('.bts-token')).toHaveCount(1)
  const token = page.locator('.bts-token').first()
  const initial = await token.getAttribute('transform')
  await expect.poll(() => token.getAttribute('transform')).not.toBe(initial)
  await panel(page).getByRole('button', { name: 'Пауза', exact: true }).click()
  const paused = await token.getAttribute('transform')
  await page.waitForTimeout(250)
  expect(await token.getAttribute('transform')).toBe(paused)
  expect(await page.evaluate(() => window.__diagram.exportXml())).toBe(baseline)
  const svg = await page.evaluate(() => window.__diagram.exportSvg())
  expect(svg).not.toContain('bts-animation-tokens')
  expect(svg).not.toContain('de-playback-active')
  await panel(page).getByRole('button', { name: 'Продолжить', exact: true }).click()
  await expect(panel(page)).toContainText('Процесс завершён')
  await panel(page).getByRole('button', { name: 'Повторить', exact: true }).click()
  await expect(page.locator('.bts-token')).toHaveCount(1)
  await panel(page).getByRole('button', { name: 'Сбросить воспроизведение' }).click()
  await expect(page.locator('.bts-token')).toHaveCount(0)
  expect(await page.evaluate(() => window.__diagram.exportXml())).toBe(baseline)
  expect(
    await page.evaluate(() => window.__diagramEvents.filter((e) => e.type === 'change')),
  ).toEqual([])
  expect(errors).toEqual([])
})

test('AND запускает два токена и join ждёт подтверждения второй ветви', async ({ page }) => {
  await open(page, parallel)
  await start(page)
  await expect(page.locator('.bts-token')).toHaveCount(2)
  await page.waitForTimeout(600)
  await page.evaluate(() => window.__diagram.pauseSimulation())
  const activePath = page.locator('.djs-connection[data-element-id="FA"] .djs-visual > path')
  const neutralStroke = await page
    .locator('.djs-connection[data-element-id="FE"] .djs-visual > path')
    .evaluate((e) => getComputedStyle(e).stroke)
  expect(await activePath.evaluate((e) => getComputedStyle(e).stroke)).not.toBe(neutralStroke)
  await expect(activePath).toHaveCSS('stroke-width', '3px')
  await page.screenshot({ path: `${OUT}and-light.png` })
  await page.evaluate(() => (document.documentElement.dataset.theme = 'dark'))
  await page.waitForTimeout(400)
  await page.screenshot({ path: `${OUT}and-dark.png` })
  await page.evaluate(() => (document.documentElement.dataset.theme = 'light'))
  await panel(page).getByRole('button', { name: 'Продолжить', exact: true }).click()
  await expect(page.locator('[data-element-id="Join"].de-playback-active').first()).toBeVisible()
  await expect(panel(page)).toContainText('Ожидание события')
  await expect(page.locator('.djs-element[data-element-id="FE"].de-playback-active')).toHaveCount(0)
  await panel(page).getByRole('button', { name: 'Продолжить: Ожидание подтверждения' }).click()
  await expect(page.locator('.djs-element[data-element-id="FE"].de-playback-active')).toHaveCount(1)
  await expect(panel(page)).toContainText('Процесс завершён')
})

test('XOR выбирается явно; цикл повторно спрашивает ветвь', async ({ page }) => {
  await open(page, loop)
  await start(page)
  await expect(panel(page)).toContainText('Выберите ветвь')
  await panel(page).getByRole('button', { name: 'Ещё раз', exact: true }).click()
  await expect(panel(page)).not.toContainText('Выберите ветвь')
  await expect(panel(page)).toContainText('Выберите ветвь')
  await panel(page).getByRole('button', { name: 'Закончить', exact: true }).click()
  await expect(page.locator('.djs-element[data-element-id="Done"].de-playback-active')).toHaveCount(
    1,
  )
  await expect(panel(page)).toContainText('Процесс завершён')
})

test('несколько стартов не запускаются одновременно; смена XML останавливает прогон', async ({
  page,
}) => {
  await open(page, multiple)
  await start(page)
  await expect(panel(page)).toContainText('Выберите начало процесса')
  expect(await page.locator('.bts-token').count()).toBe(0)
  expect(
    await page.evaluate(() => window.__diagramEvents.filter((e) => e.type === 'simulation-start')),
  ).toEqual([])
  await panel(page).getByRole('button', { name: 'Проверка процесса / Уведомление' }).click()
  await expect(page.locator('[data-element-id="FB"].de-playback-active').first()).toBeVisible()
  expect(await page.locator('[data-element-id="FA"].de-playback-active').count()).toBe(0)
  await page.evaluate((source) => window.__diagramSetXml(source), linear)
  await expect(panel(page)).toHaveCount(0)
  await expect(page.locator('.bts-token')).toHaveCount(0)
  expect(
    await page.evaluate(() => window.__diagramEvents.filter((e) => e.type === 'simulation-start')),
  ).toHaveLength(1)
})

test('одноимённые старты одного процесса запускают только выбранный экземпляр', async ({
  page,
}) => {
  const sameNames = multiple.replaceAll('name="Уведомление"', 'name="Заявка"')
  await open(page, multiple)
  await page.evaluate((source) => window.__diagramSetXml(source), sameNames)
  await page.waitForFunction(
    () => window.__diagramEvents.filter((e) => e.type === 'import').length === 3,
  )
  await start(page)
  await expect(
    panel(page).getByRole('button', { name: /^Проверка процесса \/ Заявка/ }),
  ).toHaveCount(2)
  await page.evaluate(() => window.__diagram.startSimulation('StartB'))
  await expect(page.locator('.bts-token')).toHaveCount(1)
  await expect(
    page.locator('.djs-overlays[data-container-id="StartA"] .bts-context-pad'),
  ).toBeHidden()
  await expect(page.locator('.djs-element[data-element-id="FB"].de-playback-active')).toHaveCount(1)
  expect(await page.locator('.djs-element[data-element-id="FA"].de-playback-active').count()).toBe(
    0,
  )
})

test('readOnly сохраняется после воспроизведения; тема и reduced motion видны', async ({
  page,
}) => {
  await open(page, linear, true)
  await page.evaluate(() => (document.documentElement.dataset.theme = 'dark'))
  await start(page)
  await expect(page.locator('.bts-token')).toHaveCount(1)
  const fill = await page.locator('.bts-circle').evaluate((e) => getComputedStyle(e).fill)
  expect(fill).not.toBe('none')
  await page.emulateMedia({ reducedMotion: 'reduce' })
  await expect(page.locator('.bts-animation-tokens')).toHaveCSS('visibility', 'hidden')
  await expect(page.locator('.djs-element.de-playback-active')).toHaveCount(1)
  await page.evaluate(() => window.__diagram?.toggleSimulation(false))
  const shape = page.locator('.djs-shape[data-element-id="Task"]').first()
  const before = await shape.getAttribute('transform')
  const box = await shape.boundingBox()
  if (!box) throw new Error('Фигура не видна')
  await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2)
  await page.mouse.down()
  await page.mouse.move(box.x + 120, box.y + 80, { steps: 8 })
  await page.mouse.up()
  expect(await shape.getAttribute('transform')).toBe(before)
  expect(
    await page.evaluate(() => window.__diagramEvents.filter((e) => e.type === 'change')),
  ).toEqual([])
})

test('мини-карта удерживает рамку на 20–400%, drag ограничен схемой, resize и XML безопасны', async ({
  page,
}) => {
  await open(page)
  await page.evaluate(() => {
    window.__diagram?.toggleMinimap(true)
  })
  for (let i = 0; i < 8; i++) {
    await page.evaluate(() => window.__diagram.zoomOut())
    await page.waitForTimeout(350)
  }
  async function contained() {
    const map = await page.locator('.djs-minimap .map').boundingBox()
    const indicator = await page.locator('.viewport-dom').boundingBox()
    if (!indicator) throw new Error('Мини-карта не видна')
    if (!map) throw new Error('Мини-карта не видна')
    expect(indicator.x).toBeGreaterThanOrEqual(map.x)
    expect(indicator.y).toBeGreaterThanOrEqual(map.y)
    expect(indicator.x + indicator.width).toBeLessThanOrEqual(map.x + map.width)
    expect(indicator.y + indicator.height).toBeLessThanOrEqual(map.y + map.height)
  }
  await contained()
  const scale = () =>
    page.evaluate(() => {
      const rect = document.querySelector('.de-root')?.getBoundingClientRect()
      if (!rect) throw new Error('Редактор не готов')
      return (
        rect.width /
        (window.__diagram.screenToDiagram(rect.right, rect.top).x -
          window.__diagram.screenToDiagram(rect.left, rect.top).x)
      )
    })
  expect(await scale()).toBeCloseTo(0.2, 3)
  await page.screenshot({ path: `${OUT}minimap-20.png` })
  // Несколько законченных анимаций доходят до предельного масштаба.
  for (let i = 0; i < 14; i++) {
    await page.evaluate(() => window.__diagram?.zoomIn())
    await page.waitForTimeout(350)
  }
  await contained()
  expect(await scale()).toBeCloseTo(4, 3)
  await page.screenshot({ path: `${OUT}minimap-400.png` })
  const indicator = await page.locator('.viewport-dom').boundingBox()
  if (!indicator) throw new Error('Мини-карта не видна')
  await page.mouse.move(indicator.x + indicator.width / 2, indicator.y + indicator.height / 2)
  await page.mouse.down()
  await page.mouse.move(2000, 1500, { steps: 20 })
  await page.mouse.up()
  await contained()
  const navigation = await page.evaluate(() => {
    const root = document.querySelector('.de-root')?.getBoundingClientRect()
    const map = document.querySelector<SVGSVGElement>('.djs-minimap .map svg')?.viewBox.baseVal
    if (!root || !map) throw new Error('Мини-карта не открыта')
    const top = window.__diagram.screenToDiagram(root.left, root.top)
    const bottom = window.__diagram.screenToDiagram(root.right, root.bottom)
    return {
      x: top.x,
      y: top.y,
      width: bottom.x - top.x,
      height: bottom.y - top.y,
      bounds: { x: map.x, y: map.y, width: map.width, height: map.height },
    }
  })
  for (const [position, span, start, length] of [
    [navigation.x, navigation.width, navigation.bounds.x, navigation.bounds.width],
    [navigation.y, navigation.height, navigation.bounds.y, navigation.bounds.height],
  ]) {
    if (span >= length) expect(position).toBeCloseTo(start + (length - span) / 2, 3)
    else {
      expect(position).toBeGreaterThanOrEqual(start - 0.01)
      expect(position + span).toBeLessThanOrEqual(start + length + 0.01)
    }
  }
  const beforeWheel = await page.locator('.viewport-dom').boundingBox()
  if (!beforeWheel) throw new Error('Мини-карта не видна')
  await page.locator('.djs-minimap .map').dispatchEvent('wheel', { deltaY: 150, ctrlKey: true })
  await expect
    .poll(async () => (await page.locator('.viewport-dom').boundingBox())?.width ?? 0)
    .toBeGreaterThan(beforeWheel.width)
  await page.locator('.djs-minimap .map').click({ position: { x: 10, y: 10 } })
  await page.waitForTimeout(400)
  await contained()
  await page.setViewportSize({ width: 1000, height: 700 })
  await contained()
  await page.evaluate((source) => window.__diagramSetXml(source), multiple)
  await expect(page.locator('.djs-shape[data-element-id="StartA"]').first()).toBeVisible()
  await contained()
  await page.evaluate(() => {
    window.__diagram?.toggleMinimap(false)
    window.__diagram?.toggleMinimap(true)
    window.__diagram?.fit()
  })
  await page.waitForTimeout(400)
  await contained()
})

test('режим без поддерживаемого старта честно сообщает ограничение', async ({ page }) => {
  await open(page)
  await page.evaluate((source) => window.__diagramSetXml(source), xml([], []))
  await page.waitForFunction(
    () => window.__diagramEvents.filter((e) => e.type === 'import').length === 3,
  )
  await start(page)
  await expect(panel(page)).toContainText('В схеме нет поддерживаемого начального события')
  await expect(page.locator('.bts-token')).toHaveCount(0)
  expect(
    await page.evaluate(() => window.__diagramEvents.filter((e) => e.type === 'simulation-start')),
  ).toEqual([])
})

test('event-based gateway честно ждёт сообщение или таймер и отменяет альтернативу', async ({
  page,
}) => {
  const events = xml(
    [
      { id: 'Start', type: 'startEvent', x: 100, y: 180 },
      { id: 'EventGateway', type: 'eventBasedGateway', x: 250, y: 180 },
      {
        id: 'Message',
        name: 'Получено сообщение',
        type: 'intermediateCatchEvent',
        event: 'messageEventDefinition',
        x: 450,
        y: 70,
      },
      {
        id: 'Timer',
        name: 'Истёк таймер',
        type: 'intermediateCatchEvent',
        event: 'timerEventDefinition',
        x: 450,
        y: 300,
      },
      { id: 'End', type: 'endEvent', x: 750, y: 180 },
    ],
    [
      { id: 'F1', from: 'Start', to: 'EventGateway' },
      { id: 'FM', from: 'EventGateway', to: 'Message' },
      { id: 'FT', from: 'EventGateway', to: 'Timer' },
      { id: 'FME', from: 'Message', to: 'End' },
      { id: 'FTE', from: 'Timer', to: 'End' },
    ],
  )
  await open(page, events)
  await start(page)
  await expect(panel(page)).toContainText('Ожидание события')
  await expect(panel(page).getByRole('button', { name: /^Продолжить:/ })).toHaveCount(2)
  await panel(page).getByRole('button', { name: 'Продолжить: Истёк таймер' }).click()
  await expect(page.locator('.djs-element[data-element-id="FTE"].de-playback-active')).toHaveCount(
    1,
  )
  await expect(page.locator('.djs-element[data-element-id="FME"].de-playback-active')).toHaveCount(
    0,
  )
  await expect(panel(page)).toContainText('Процесс завершён')
})

test('OR join не превращает внутреннее all-completed в публичное событие', async ({ page }) => {
  const errors = await open(page, parallel.replaceAll('parallelGateway', 'inclusiveGateway'))
  await start(page)
  await expect(page.locator('.bts-token')).toHaveCount(2)
  await expect(panel(page)).toContainText('Ожидание события')
  await panel(page).getByRole('button', { name: 'Продолжить: Ожидание подтверждения' }).click()
  await expect(panel(page)).toContainText('Процесс завершён')
  expect(errors).toEqual([])
})
