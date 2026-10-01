import { describe, expect, it } from 'vitest'
import { buildLocalBpmn } from './local-bpmn'

describe('локальная сборка BPMN', () => {
  it('создаёт корректный XML с шагами и экранированным названием', () => {
    const xml = buildLocalBpmn(
      'Проверка & согласование',
      'Оператор проверяет заявку. Руководитель согласует договор.',
    )
    const document = new DOMParser().parseFromString(xml, 'application/xml')
    const parserError = document.getElementsByTagName('parsererror')[0]
    const bpmn = 'http://www.omg.org/spec/BPMN/20100524/MODEL'

    expect(parserError).toBeUndefined()
    expect(document.getElementsByTagNameNS(bpmn, 'process')[0]?.getAttribute('name')).toBe(
      'Проверка & согласование',
    )
    expect(
      Array.from(document.getElementsByTagNameNS(bpmn, 'task')).map((task) =>
        task.getAttribute('name'),
      ),
    ).toEqual(['Оператор проверяет заявку', 'Руководитель согласует договор'])
    expect(document.getElementsByTagNameNS(bpmn, 'sequenceFlow')).toHaveLength(3)
  })
})
