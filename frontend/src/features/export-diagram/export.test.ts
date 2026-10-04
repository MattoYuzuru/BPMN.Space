import { exportDiagram, exportFileName } from './export'

describe('exportFileName', () => {
  it('убирает запрещённые в именах файлов символы', () => {
    expect(exportFileName('Техприсоединение: заявка / договор', 3, 'bpmn')).toBe(
      'Техприсоединение заявка договор, версия 3.bpmn',
    )
    expect(exportFileName('   ', 1, 'png')).toBe('Схема, версия 1.png')
    expect(exportFileName('А'.repeat(120), 2, 'svg')).toHaveLength(80 + ', версия 2.svg'.length)
  })
})

describe('exportDiagram: onSaved', () => {
  const base = { versionId: 'v1', versionNumber: 1, title: 'Схема', editor: null }

  // jsdom не умеет скачивать файлы по ссылке.
  beforeEach(() => {
    vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {})
  })
  afterEach(() => vi.restoreAllMocks())

  it('.bpmn отдан браузеру — onSaved вызван', async () => {
    const onSaved = vi.fn()
    await exportDiagram({ ...base, format: 'bpmn', onSaved })
    expect(onSaved).toHaveBeenCalledOnce()
  })

  it('SVG и PNG рисует редактор; успех — onSaved', async () => {
    URL.createObjectURL = vi.fn(() => 'blob:x')
    URL.revokeObjectURL = vi.fn()
    const editor = {
      exportSvg: vi.fn(async () => '<svg/>'),
      exportPng: vi.fn(async () => new Blob(['png'])),
    } as never
    const onSaved = vi.fn()
    await exportDiagram({ ...base, format: 'svg', editor, onSaved })
    await exportDiagram({ ...base, format: 'png', editor, onSaved })
    expect(onSaved).toHaveBeenCalledTimes(2)
  })

  it('редактор не загрузился — ошибка, onSaved не вызван', async () => {
    const onSaved = vi.fn()
    await exportDiagram({ ...base, format: 'png', onSaved })
    expect(onSaved).not.toHaveBeenCalled()
  })
})
