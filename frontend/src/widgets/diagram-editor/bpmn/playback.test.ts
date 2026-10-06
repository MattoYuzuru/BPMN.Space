import { isProcessStart, sequenceChoices } from './playback'
import { cleanPlaybackSvg } from './runtime-colors'

const process = { id: 'P', type: 'bpmn:Process' }
const start = { id: 'S', type: 'bpmn:StartEvent' }

describe('выбор начального события', () => {
  it('начало не требует none event: таймер и сообщение доступны как явный сценарный запуск', () => {
    expect(
      isProcessStart({
        element: start,
        event: { type: 'timer' },
        scope: { element: process, parent: null, running: false, active: true },
      }),
    ).toBe(true)
  })
  it('исключает вложенное событие и новый запуск уже идущего процесса', () => {
    const parent = { element: process, parent: null, running: true, active: true }
    expect(
      isProcessStart({ element: start, event: { type: 'none' }, scope: { ...parent, parent } }),
    ).toBe(false)
    expect(isProcessStart({ element: start, event: { type: 'none' }, scope: parent })).toBe(false)
  })
  it('выбор XOR содержит только sequence flows, без message flows', () => {
    const flow = { id: 'F', type: 'bpmn:SequenceFlow' }
    expect(
      sequenceChoices({
        id: 'X',
        type: 'bpmn:ExclusiveGateway',
        outgoing: [flow, { id: 'M', type: 'bpmn:MessageFlow' }],
      }),
    ).toEqual([flow])
  })
})

describe('экспорт рисунка во время воспроизведения', () => {
  it('убирает токены и временные DOM цвета, оставляет исходную геометрию и цвет', () => {
    const output = cleanPlaybackSvg(
      '<svg xmlns="http://www.w3.org/2000/svg"><g class="djs-element de-simulation-color de-playback-active" style="--de-sim-fill: red; --de-sim-stroke: blue;"><rect x="10" stroke="green"/></g><g class="bts-animation-tokens"><circle/></g></svg>',
    )
    expect(output).not.toContain('bts-animation-tokens')
    expect(output).not.toContain('de-playback-active')
    expect(output).not.toContain('--de-sim-')
    expect(output).toContain('stroke="green"')
    expect(output).toContain('x="10"')
  })
})
