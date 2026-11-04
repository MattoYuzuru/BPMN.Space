import assert from 'node:assert/strict'
import { once } from 'node:events'
import { readdir, readFile } from 'node:fs/promises'
import { test } from 'node:test'
import { WorkerPool } from '../pool.mjs'
import { createToolsServer } from '../server.mjs'
import { layout, lint, parse } from '../tools.mjs'

const sample = `<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL" id="D" targetNamespace="urn:test"><bpmn:process id="P"><bpmn:startEvent id="S" name="Начало"><bpmn:outgoing>F1</bpmn:outgoing></bpmn:startEvent><bpmn:task id="T" name="Работа"><bpmn:incoming>F1</bpmn:incoming><bpmn:outgoing>F2</bpmn:outgoing></bpmn:task><bpmn:endEvent id="E" name="Конец"><bpmn:incoming>F2</bpmn:incoming></bpmn:endEvent><bpmn:sequenceFlow id="F1" sourceRef="S" targetRef="T"/><bpmn:sequenceFlow id="F2" sourceRef="T" targetRef="E"/></bpmn:process></bpmn:definitions>`

test('настоящий layout делает DI, готовый DI остаётся байт-в-байт, lint проверяет XML', async () => {
  const result = await layout(sample)
  assert.match(result.xml, /BPMNShape/)
  assert.equal((await lint(result.xml)).issues.filter((i) => i.severity === 'error').length, 0)
  assert.equal((await layout(result.xml)).xml, result.xml)
})

test('новая раскладка вмещает длинную подпись, не теряет текст и сохраняет прямые сегменты', async () => {
  const label =
    'Подготовить и согласовать полный комплект технических документов для восстановления энергоснабжения потребителей после завершения ремонтных работ и проверки готовности оборудования к вводу в эксплуатацию'
  const result = await layout(sample.replace('name="Работа"', `name="${label}"`))
  const definitions = await parse(result.xml)
  const elements = definitions.diagrams[0].plane.planeElement
  const task = elements.find((element) => element.bpmnElement?.id === 'T')
  assert.equal(task.bpmnElement.name, label)
  assert.equal(task.bounds.width, 160)
  assert.ok(task.bounds.height >= 160, '200 символов требуют большей высоты, чем стандартные 80')
  for (const edge of elements.filter((element) => element.$type === 'bpmndi:BPMNEdge')) {
    for (let index = 1; index < edge.waypoint.length; index += 1) {
      const before = edge.waypoint[index - 1]
      const after = edge.waypoint[index]
      assert.ok(before.x === after.x || before.y === after.y, edge.bpmnElement.id)
    }
  }
  assert.equal((await layout(result.xml)).xml, result.xml)
  assert.deepEqual((await lint(result.xml)).issues, [])
})

test('известный fake-join имеет предупреждение настоящего bpmnlint', async () => {
  const xml = await readFile(
    new URL('../../../backend/app/fixtures/bpmn/tp861_v1.bpmn', import.meta.url),
    'utf8',
  )
  assert.ok(
    (await lint(xml)).issues.some(
      (i) => i.rule === 'fake-join' && i.element_id === 'Task_CheckCompleteness',
    ),
  )
})

test('примеры для жюри и BPMN-фикстуры проходят настоящий recommended lint', async () => {
  for (const directory of ['../../../examples/', '../../../backend/app/fixtures/bpmn/']) {
    const root = new URL(directory, import.meta.url)
    const files = (await readdir(root, { recursive: true })).filter((name) =>
      name.endsWith('.bpmn'),
    )
    assert.ok(files.length > 0, directory)
    for (const name of files) {
      const xml = await readFile(new URL(name, root), 'utf8')
      const errors = (await lint(xml)).issues.filter((issue) => issue.severity === 'error')
      assert.deepEqual(errors, [], `${directory}${name}`)
    }
  }
})

test('HTTP порт имеет health, layout и bounded failure, не возвращает success на плохом XML', async () => {
  const server = createToolsServer().listen(0, '127.0.0.1')
  await once(server, 'listening')
  const url = `http://127.0.0.1:${server.address().port}`
  try {
    assert.equal((await fetch(`${url}/health`)).status, 200)
    const response = await fetch(`${url}/layout`, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ xml: sample }),
    })
    assert.equal(response.status, 200)
    assert.match((await response.json()).xml, /BPMNShape/)
    assert.equal(
      (await fetch(`${url}/lint`, { method: 'POST', body: JSON.stringify({ xml: 'not XML' }) }))
        .status,
      422,
    )
    assert.equal(
      (await fetch(`${url}/layout`, { method: 'POST', body: 'broken JSON' })).status,
      422,
    )
  } finally {
    server.close()
    await once(server, 'close')
  }
})

test('worker deadline выдаёт 504 и health остаётся доступен', async () => {
  const server = createToolsServer({ deadlineMs: 1 }).listen(0, '127.0.0.1')
  await once(server, 'listening')
  const url = `http://127.0.0.1:${server.address().port}`
  try {
    const response = await fetch(`${url}/layout`, {
      method: 'POST',
      body: JSON.stringify({ xml: sample }),
    })
    assert.equal(response.status, 504)
    assert.equal((await fetch(`${url}/health`)).status, 200)
  } finally {
    server.close()
    await once(server, 'close')
  }
})

const post = (url, path = 'layout') =>
  fetch(`${url}/${path}`, { method: 'POST', body: JSON.stringify({ xml: sample }) })

async function withServer(options, run) {
  const server = createToolsServer(options).listen(0, '127.0.0.1')
  await once(server, 'listening')
  try {
    await run(`http://127.0.0.1:${server.address().port}`, server)
  } finally {
    server.close()
    await once(server, 'close')
  }
}

test('очередь пула обслуживает всплеск запросов без 503', async () => {
  await withServer({}, async (url, server) => {
    const statuses = await Promise.all(
      Array.from({ length: 8 }, async () => (await post(url)).status),
    )
    assert.deepEqual(statuses, Array(8).fill(200))
    assert.ok(server.pool.spawned <= 2, 'worker-ы переиспользуются, а не создаются на запрос')
    assert.equal((await fetch(`${url}/health`)).status, 200)
  })
})

test('переполнение очереди даёт 503, health остаётся доступен', async () => {
  await withServer({ poolSize: 1, queueLimit: 1 }, async (url) => {
    const statuses = await Promise.all(
      Array.from({ length: 8 }, async () => (await post(url)).status),
    )
    assert.ok(statuses.includes(200))
    assert.ok(statuses.includes(503))
    assert.ok(statuses.every((status) => status === 200 || status === 503))
    assert.equal((await fetch(`${url}/health`)).status, 200)
  })
})

test('worker пересоздаётся после лимита задач', async () => {
  await withServer({ poolSize: 1, maxJobsPerWorker: 2 }, async (url, server) => {
    for (let index = 0; index < 5; index += 1) assert.equal((await post(url)).status, 200)
    assert.equal(server.pool.spawned, 3)
  })
})

test('таймаут пересоздаёт worker и следующий запрос проходит', async () => {
  const pool = new WorkerPool({ size: 1, jobTimeoutMs: 1 })
  await assert.rejects(pool.run('layout', sample), { code: 'timeout', status: 504 })
  pool.jobTimeoutMs = 30_000
  const message = await pool.run('layout', sample)
  assert.equal(message.ok, true)
  assert.equal(pool.spawned, 2)
  await pool.close()
})

test('сбой worker даёт 503, пул продолжает работать', async () => {
  const pool = new WorkerPool({
    size: 1,
    workerUrl: new URL('./crash-worker.mjs', import.meta.url),
  })
  await assert.rejects(pool.run('layout', 'crash'), { code: 'crash', status: 503 })
  const message = await pool.run('layout', 'ok')
  assert.equal(message.ok, true)
  await pool.close()
})

test('отмена ожидающей и выполняющейся задачи освобождает пул', async () => {
  const pool = new WorkerPool({ size: 1, queueLimit: 4 })
  const running = new AbortController()
  const waiting = new AbortController()
  const first = pool.run('layout', sample, running.signal)
  const second = pool.run('layout', sample, waiting.signal)
  waiting.abort()
  running.abort()
  await assert.rejects(first, { code: 'cancelled' })
  await assert.rejects(second, { code: 'cancelled' })
  assert.equal((await pool.run('layout', sample)).ok, true)
  await pool.close()
})

test('HTTP-ответ при сбое worker несёт code=crash', async () => {
  const workerUrl = new URL('./crash-worker.mjs', import.meta.url)
  await withServer({ workerUrl, poolSize: 1 }, async (url) => {
    const response = await fetch(`${url}/layout`, {
      method: 'POST',
      body: JSON.stringify({ xml: 'crash' }),
    })
    assert.equal(response.status, 503)
    assert.equal((await response.json()).code, 'crash')
  })
})

test('правка маршрутизации bpmn-auto-layout применена (patches/apply.mjs)', async () => {
  // Без неё граф на ~100 узлов раскладывается дольше таймаута сервиса: см. patches/apply.mjs.
  const dist = await readFile(
    new URL('../node_modules/bpmn-auto-layout/dist/index.js', import.meta.url),
    'utf8',
  )
  assert.ok(dist.includes('BPMN Space: exact bounding-box prefilter'))
})
