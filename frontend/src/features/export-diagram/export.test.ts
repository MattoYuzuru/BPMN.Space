import { exportFileName } from './export'

describe('exportFileName', () => {
  it('убирает запрещённые в именах файлов символы', () => {
    expect(exportFileName('Техприсоединение: заявка / договор', 3, 'bpmn')).toBe(
      'Техприсоединение заявка договор, версия 3.bpmn',
    )
    expect(exportFileName('   ', 1, 'png')).toBe('Схема, версия 1.png')
    expect(exportFileName('А'.repeat(120), 2, 'svg')).toHaveLength(80 + ', версия 2.svg'.length)
  })
})
