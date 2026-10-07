import { execFile, spawn } from 'node:child_process'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { promisify } from 'node:util'
import { expect, test } from '@playwright/test'
import type { DiagramEditorHandle } from '../src/widgets/diagram-editor/types'

declare const window: Window & {
  __diagram: DiagramEditorHandle
  __diagramSetXml: (xml: string) => void
  __diagramEvents: Array<{ type: string }>
}

const root = fileURLToPath(new URL('../../', import.meta.url))
const outputRoot = fileURLToPath(new URL('../../reports/tmp/generated-ir/', import.meta.url))
let output: string
const cases = [
  'xor',
  'and',
  'nested',
  'loop',
  'starts',
  'parallel_ends',
  'energy_incident',
  'logistics_order',
  'service_release',
] as const

test.beforeAll(async ({ baseURL }, info) => {
  if (!baseURL) throw new Error('Не задан адрес canvas-стенда')
  test.setTimeout(90_000)
  output = `${outputRoot}canvas-${info.parallelIndex}/`
  // Отдельный HTTP-процесс: recorded адаптер проходит тот же runtime layout/lint, что backend.
  const server = spawn(
    'node',
    [
      '--input-type=module',
      '-e',
      "import {createToolsServer} from './server.mjs';const s=createToolsServer();s.listen(0,'127.0.0.1',()=>process.stdout.write(String(s.address().port)+'\\n'));process.on('SIGTERM',()=>s.close());",
    ],
    { cwd: `${root}infra/bpmn-tools`, stdio: ['ignore', 'pipe', 'pipe'] },
  )
  try {
    const port = await new Promise<string>((resolve, reject) => {
      const timeout = setTimeout(() => reject(new Error('Не запустился bpmn-tools')), 10_000)
      server.once('error', (error) => {
        clearTimeout(timeout)
        reject(error)
      })
      server.stdout.once('data', (data) => {
        clearTimeout(timeout)
        resolve(data.toString().trim())
      })
      server.once('exit', (code) => {
        clearTimeout(timeout)
        reject(new Error(`bpmn-tools остановился: ${code}`))
      })
    })
    await promisify(execFile)(
      'uv',
      [
        'run',
        '--directory',
        `${root}backend`,
        'python',
        'scripts/export_ir_checks.py',
        '--tools-url',
        `http://127.0.0.1:${port}`,
        '--output',
        output,
      ],
      { cwd: root, timeout: 60_000 },
    )
  } finally {
    server.kill('SIGTERM')
  }
})

for (const scenario of cases) {
  test(`сгенерированный ${scenario}: импорт, семантический экспорт и видимое воспроизведение`, async ({
    page,
  }) => {
    const xml = readFileSync(`${output}${scenario}.bpmn`, 'utf8')
    const ir = JSON.parse(readFileSync(`${output}${scenario}.ir.json`, 'utf8'))
    const errors: string[] = []
    page.on('pageerror', (error) => errors.push(error.message))
    await page.goto('/dev/diagram')
    await page.waitForFunction(
      () => window.__diagramEvents?.filter((event) => event.type === 'import').length === 1,
    )
    await page.evaluate((source) => window.__diagramSetXml(source), xml)
    await page.waitForFunction(
      () => window.__diagramEvents?.filter((event) => event.type === 'import').length === 2,
    )
    await page.evaluate(() => window.__diagram.fit())
    await page.waitForTimeout(400)
    const frame = await page.locator('.djs-container').boundingBox()
    const viewport = await page.locator('.djs-container > svg > g.viewport').boundingBox()
    expect(frame).not.toBeNull()
    expect(viewport).not.toBeNull()
    if (frame && viewport) {
      expect(viewport.x).toBeGreaterThanOrEqual(frame.x)
      expect(viewport.y).toBeGreaterThanOrEqual(frame.y)
      expect(viewport.x + viewport.width).toBeLessThanOrEqual(frame.x + frame.width)
      expect(viewport.y + viewport.height).toBeLessThanOrEqual(frame.y + frame.height)
    }
    for (const node of ir.nodes) {
      await expect(page.locator(`.djs-shape[data-element-id="${node.id}"]`)).toBeVisible()
    }
    const overflowing = await page.evaluate((nodes) => {
      return nodes
        .filter((node: { id: string; type: string }) => node.type === 'task')
        .flatMap((node: { id: string }) => {
          const visual = document.querySelector<SVGGElement>(
            `.djs-shape[data-element-id="${node.id}"] .djs-visual`,
          )
          const text = visual?.querySelector<SVGTextElement>('text')
          const rectangle = visual?.querySelector<SVGRectElement>('rect')
          if (!text || !rectangle) return [node.id]
          const label = text.getBBox()
          const box = rectangle.getBBox()
          return label.x < box.x - 1 ||
            label.y < box.y - 1 ||
            label.x + label.width > box.x + box.width + 1 ||
            label.y + label.height > box.y + box.height + 1
            ? [node.id]
            : []
        })
    }, ir.nodes)
    expect(overflowing, 'Полная подпись каждой задачи остаётся внутри её прямоугольника').toEqual(
      [],
    )
    const exported = await page.evaluate(() => window.__diagram.exportXml())
    const semantics = await page.evaluate(
      ([before, after]) => {
        const parse = (source: string) => {
          const document = new DOMParser().parseFromString(source, 'application/xml')
          if (document.querySelector('parsererror')) throw new Error('Невалидный экспорт XML')
          return Array.from(
            document.getElementsByTagNameNS('http://www.omg.org/spec/BPMN/20100524/MODEL', '*'),
          )
            .map((element) =>
              JSON.stringify({
                tag: element.localName,
                attributes: Array.from(element.attributes)
                  .filter((attribute) => attribute.namespaceURI !== 'http://www.w3.org/2000/xmlns/')
                  .filter(
                    (attribute) =>
                      element.localName !== 'definitions' ||
                      !['exporter', 'exporterVersion'].includes(attribute.localName),
                  )
                  .map((attribute) => [attribute.localName, attribute.value])
                  .sort(),
                text: element.children.length ? '' : element.textContent?.trim(),
              }),
            )
            .sort()
        }
        return [parse(before), parse(after)]
      },
      [xml, exported],
    )
    expect(semantics[1]).toEqual(semantics[0])
    const svg = await page.evaluate(() => window.__diagram.exportSvg())
    expect(svg).toContain('<svg')
    await page.evaluate(() => window.__diagram.toggleSimulation(true))
    const starts = ir.nodes.filter((node: { type: string }) => node.type === 'start')
    if (starts.length > 1) {
      await page.evaluate((id) => window.__diagram.startSimulation(id), starts[0].id)
    }
    await expect(page.locator('.bts-token').first()).toBeVisible()
    await page.evaluate(() => window.__diagram.pauseSimulation())
    expect(await page.evaluate(() => window.__diagram.exportXml())).toBe(exported)
    expect(errors).toEqual([])
    if (scenario.includes('_') && !scenario.startsWith('parallel')) {
      await page.screenshot({ path: `${output}${scenario}-canvas.png` })
    }
  })
}
