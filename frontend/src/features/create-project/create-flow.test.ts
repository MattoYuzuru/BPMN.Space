import { describe, expect, it, vi } from 'vitest'
import { type CreateFlowDeps, runCreateFlow } from './create-flow'

function deps(overrides: Partial<CreateFlowDeps> = {}) {
  const calls: string[] = []
  const value: CreateFlowDeps = {
    createProject: vi.fn(async (body) => {
      calls.push('create')
      return { id: 'p1', title: body.title }
    }),
    addText: vi.fn(async () => {
      calls.push('text')
    }),
    uploadFile: vi.fn(async (_id, file) => {
      calls.push(`file:${file.name}`)
    }),
    startBuild: vi.fn(async () => {
      calls.push('build')
    }),
    fetchProject: vi.fn(async () => ({ sources: [{ status: 'ready' }] })),
    poll: { intervalMs: 1, timeoutMs: 5 },
    ...overrides,
  }
  return { calls, value }
}

const file = (name: string) => new File(['x'], name)

describe('runCreateFlow', () => {
  it('создаёт проект, добавляет текст и файлы по порядку и запускает сборку', async () => {
    const { calls, value } = deps()

    const result = await runCreateFlow(
      {
        title: 'Приёмка',
        description: '  Мастер принимает оборудование.  ',
        files: [file('a.pdf'), file('b.md')],
      },
      value,
    )

    expect(calls).toEqual(['create', 'text', 'file:a.pdf', 'file:b.md', 'build'])
    expect(value.addText).toHaveBeenCalledWith('p1', {
      kind: 'text',
      title: 'Описание процесса',
      content: 'Мастер принимает оборудование.',
    })
    expect(result).toMatchObject({ projectId: 'p1', sources: 3, building: true, failures: [] })
  })

  it('пустой проект без описания и файлов: источников нет, сборка не запускается', async () => {
    const { calls, value } = deps()

    const result = await runCreateFlow({ title: 'Пустой', description: '  ', files: [] }, value)

    expect(calls).toEqual(['create'])
    expect(result).toMatchObject({ sources: 0, building: false, failures: [] })
  })

  it('сборка запускается и от одного только файла', async () => {
    const { calls, value } = deps()

    await runCreateFlow({ title: 'Файл', description: '', files: [file('a.docx')] }, value)

    expect(calls).toEqual(['create', 'file:a.docx', 'build'])
  })

  it('ошибка создания проекта выбрасывается, остальное не запускается', async () => {
    const { value } = deps({ createProject: vi.fn().mockRejectedValue(new Error('нет')) })

    await expect(
      runCreateFlow({ title: 'T', description: 'текст', files: [file('a.pdf')] }, value),
    ).rejects.toThrow('нет')
    expect(value.addText).not.toHaveBeenCalled()
    expect(value.uploadFile).not.toHaveBeenCalled()
    expect(value.startBuild).not.toHaveBeenCalled()
  })

  it('сбой текста не мешает файлам и сборке, но попадает в итог', async () => {
    const { value } = deps({ addText: vi.fn().mockRejectedValue(new Error('500')) })

    const result = await runCreateFlow(
      { title: 'T', description: 'текст', files: [file('a.pdf')] },
      value,
    )

    expect(result.sources).toBe(1)
    expect(result.building).toBe(true)
    expect(result.failures).toEqual(['описание не добавлено'])
  })

  it('если ни один источник не добавлен, сборка не стартует', async () => {
    const { value } = deps({
      addText: vi.fn().mockRejectedValue(new Error('500')),
      uploadFile: vi.fn().mockRejectedValue(new Error('500')),
    })

    const result = await runCreateFlow(
      { title: 'T', description: 'текст', files: [file('a.pdf')] },
      value,
    )

    expect(value.startBuild).not.toHaveBeenCalled()
    expect(result.failures).toEqual(['описание не добавлено', '«a.pdf» не загружен'])
  })

  it('сбой запуска сборки сообщается, проект остаётся', async () => {
    const { value } = deps({ startBuild: vi.fn().mockRejectedValue(new Error('409')) })

    const result = await runCreateFlow({ title: 'T', description: 'текст', files: [] }, value)

    expect(result).toMatchObject({ projectId: 'p1', sources: 1, building: false })
    expect(result.failures).toEqual(['схема не запущена'])
  })

  it('неподдерживаемый формат пропускается без запроса', async () => {
    const { value } = deps()

    const result = await runCreateFlow(
      { title: 'T', description: '', files: [file('photo.png')] },
      value,
    )

    expect(value.uploadFile).not.toHaveBeenCalled()
    expect(result.failures).toEqual(['формат «photo.png» не поддерживается'])
  })

  it('сборка ждёт, пока документы разберутся: processing -> ready', async () => {
    const states = [[{ status: 'processing' }], [{ status: 'processing' }], [{ status: 'ready' }]]
    const fetchProject = vi.fn(async () => ({ sources: states.shift() ?? [{ status: 'ready' }] }))
    const { calls, value } = deps({ fetchProject, poll: { intervalMs: 1, timeoutMs: 50 } })

    const result = await runCreateFlow(
      { title: 'T', description: '', files: [file('a.pdf')] },
      value,
    )

    expect(fetchProject).toHaveBeenCalledTimes(3)
    expect(calls).toEqual(['create', 'file:a.pdf', 'build'])
    expect(result).toMatchObject({ building: true, waitTimedOut: false, failures: [] })
  })

  it('без файлов состояние проекта не опрашивается', async () => {
    const { value } = deps()

    await runCreateFlow({ title: 'T', description: 'текст', files: [] }, value)

    expect(value.fetchProject).not.toHaveBeenCalled()
  })

  it('источник со статусом failed не блокирует сборку', async () => {
    const { value } = deps({
      fetchProject: vi.fn(async () => ({ sources: [{ status: 'failed' }, { status: 'ready' }] })),
    })

    const result = await runCreateFlow(
      { title: 'T', description: '', files: [file('a.pdf')] },
      value,
    )

    expect(result.building).toBe(true)
  })

  it('по истечении лимита сборка не запускается, а проект остаётся', async () => {
    const fetchProject = vi.fn(async () => ({ sources: [{ status: 'processing' }] }))
    const { value } = deps({ fetchProject, poll: { intervalMs: 1, timeoutMs: 4 } })

    const result = await runCreateFlow(
      { title: 'T', description: 'текст', files: [file('a.docx')] },
      value,
    )

    expect(fetchProject).toHaveBeenCalledTimes(4)
    expect(value.startBuild).not.toHaveBeenCalled()
    expect(result).toMatchObject({
      projectId: 'p1',
      building: false,
      waitTimedOut: true,
      failures: [],
    })
  })

  it('сбой опроса временный: следующая попытка проходит', async () => {
    const fetchProject = vi
      .fn()
      .mockRejectedValueOnce(new Error('сеть'))
      .mockResolvedValue({ sources: [{ status: 'ready' }] })
    const { value } = deps({ fetchProject })

    const result = await runCreateFlow(
      { title: 'T', description: '', files: [file('a.pdf')] },
      value,
    )

    expect(result.building).toBe(true)
  })

  it('постоянный сбой опроса заканчивается таймаутом, а не ошибкой', async () => {
    const { value } = deps({ fetchProject: vi.fn().mockRejectedValue(new Error('сеть')) })

    const result = await runCreateFlow(
      { title: 'T', description: '', files: [file('a.pdf')] },
      value,
    )

    expect(result.waitTimedOut).toBe(true)
    expect(value.startBuild).not.toHaveBeenCalled()
  })

  it('отмена прерывает ожидание без сборки', async () => {
    const controller = new AbortController()
    const fetchProject = vi.fn(async () => {
      controller.abort()
      return { sources: [{ status: 'processing' }] }
    })
    const { value } = deps({ fetchProject, poll: { intervalMs: 1000, timeoutMs: 60_000 } })

    const result = await runCreateFlow(
      { title: 'T', description: '', files: [file('a.pdf')], signal: controller.signal },
      value,
    )

    expect(fetchProject).toHaveBeenCalledTimes(1)
    expect(value.startBuild).not.toHaveBeenCalled()
    expect(result).toMatchObject({ building: false, waitTimedOut: false })
  })

  it('сбой загрузки файла не ждёт разбора', async () => {
    const { value } = deps({ uploadFile: vi.fn().mockRejectedValue(new Error('500')) })

    await runCreateFlow({ title: 'T', description: 'текст', files: [file('a.pdf')] }, value)

    expect(value.fetchProject).not.toHaveBeenCalled()
  })
})
