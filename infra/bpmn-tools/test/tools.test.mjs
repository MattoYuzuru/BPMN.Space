import assert from 'node:assert/strict'
import { once } from 'node:events'
import { readFile } from 'node:fs/promises'
import { test } from 'node:test'
import { createToolsServer } from '../server.mjs'
import { layout, lint } from '../tools.mjs'

const sample = `<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL" id="D" targetNamespace="urn:test"><bpmn:process id="P"><bpmn:startEvent id="S" name="Начало"><bpmn:outgoing>F1</bpmn:outgoing></bpmn:startEvent><bpmn:task id="T" name="Работа"><bpmn:incoming>F1</bpmn:incoming><bpmn:outgoing>F2</bpmn:outgoing></bpmn:task><bpmn:endEvent id="E" name="Конец"><bpmn:incoming>F2</bpmn:incoming></bpmn:endEvent><bpmn:sequenceFlow id="F1" sourceRef="S" targetRef="T"/><bpmn:sequenceFlow id="F2" sourceRef="T" targetRef="E"/></bpmn:process></bpmn:definitions>`

test('настоящий layout делает DI, готовый DI остаётся байт-в-байт, lint проверяет XML', async () => {
  const result = await layout(sample)
  assert.match(result.xml, /BPMNShape/)
  assert.equal((await lint(result.xml)).issues.filter((i) => i.severity === 'error').length, 0)
  assert.equal((await layout(result.xml)).xml, result.xml)
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

test('конкурентные запросы ограничены двумя workers', async () => {
  const server = createToolsServer().listen(0, '127.0.0.1')
  await once(server, 'listening')
  const url = `http://127.0.0.1:${server.address().port}`
  try {
    const statuses = await Promise.all(
      Array.from(
        { length: 8 },
        async () =>
          (await fetch(`${url}/layout`, { method: 'POST', body: JSON.stringify({ xml: sample }) }))
            .status,
      ),
    )
    assert.ok(statuses.filter((status) => status === 200).length <= 2)
    assert.ok(statuses.includes(503))
    assert.equal((await fetch(`${url}/health`)).status, 200)
  } finally {
    server.close()
    await once(server, 'close')
  }
})
