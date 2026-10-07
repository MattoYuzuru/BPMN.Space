import { createChangeEmitter } from './change-emitter'

function setup(xml: () => string) {
  const onChange = vi.fn()
  const onError = vi.fn()
  const onChangePending = vi.fn()
  const serialize = vi.fn(async () => xml())
  const emitter = createChangeEmitter({ delay: 400, serialize, onChange, onChangePending, onError })
  return { emitter, onChange, onChangePending, onError, serialize }
}

describe('createChangeEmitter', () => {
  beforeEach(() => vi.useFakeTimers())
  afterEach(() => vi.useRealTimers())

  it('выдаёт XML не раньше чем через 400 мс после последней правки', async () => {
    let version = 1
    const { emitter, onChange } = setup(() => `<v${version}/>`)
    emitter.setBaseline('<v0/>')
    emitter.notify('execute')
    await vi.advanceTimersByTimeAsync(300)
    version = 2
    emitter.notify('execute')
    await vi.advanceTimersByTimeAsync(300)
    expect(onChange).not.toHaveBeenCalled()
    await vi.advanceTimersByTimeAsync(100)
    expect(onChange).toHaveBeenCalledTimes(1)
    expect(onChange).toHaveBeenCalledWith('<v2/>')
  })

  it('игнорирует очистку стека при импорте', async () => {
    const { emitter, serialize, onChangePending } = setup(() => '<new/>')
    emitter.notify('clear')
    await vi.advanceTimersByTimeAsync(1000)
    expect(serialize).not.toHaveBeenCalled()
    expect(emitter.hasPending()).toBe(false)
    expect(onChangePending).not.toHaveBeenCalled()
  })

  it('сразу защищает правку до XML и снимает защиту после его выдачи', async () => {
    const { emitter, serialize, onChange, onChangePending } = setup(() => '<new/>')
    emitter.notify('execute')
    expect(onChangePending).toHaveBeenCalledWith(true)
    expect(serialize).not.toHaveBeenCalled()
    await vi.advanceTimersByTimeAsync(399)
    expect(onChange).not.toHaveBeenCalled()
    expect(onChangePending.mock.calls).toEqual([[true]])
    await vi.advanceTimersByTimeAsync(1)
    expect(onChange).toHaveBeenCalledWith('<new/>')
    expect(onChangePending.mock.calls).toEqual([[true], [false]])
  })

  it('cancel снимает раннюю защиту и не выдаёт отвергнутый черновик', async () => {
    const { emitter, onChange, onChangePending } = setup(() => '<discarded/>')
    emitter.notify('execute')
    emitter.cancel()
    await vi.advanceTimersByTimeAsync(400)
    expect(onChange).not.toHaveBeenCalled()
    expect(onChangePending.mock.calls).toEqual([[true], [false]])
  })

  it('старый экспорт не снимает защиту команды, пришедшей во время сериализации', async () => {
    let resolve: (xml: string) => void = () => {}
    const onChange = vi.fn()
    const onChangePending = vi.fn()
    const serialize = vi
      .fn()
      .mockImplementationOnce(
        () =>
          new Promise<string>((done) => {
            resolve = done
          }),
      )
      .mockResolvedValue('<latest/>')
    const emitter = createChangeEmitter({ delay: 400, serialize, onChange, onChangePending })
    emitter.notify('execute')
    await vi.advanceTimersByTimeAsync(400)
    emitter.notify('execute')
    resolve('<first/>')
    await Promise.resolve()
    expect(onChange).toHaveBeenCalledWith('<first/>')
    expect(onChangePending.mock.calls).toEqual([[true]])
    await vi.advanceTimersByTimeAsync(400)
    expect(onChangePending.mock.calls).toEqual([[true], [false]])
  })

  it('учитывает undo и redo как правки', async () => {
    const { emitter, onChange } = setup(() => '<undone/>')
    emitter.setBaseline('<edited/>')
    emitter.notify('undo')
    await vi.advanceTimersByTimeAsync(400)
    expect(onChange).toHaveBeenCalledWith('<undone/>')
  })

  it('не шлёт XML, если он совпал с базовым (правку отменили) или с уже выданным', async () => {
    let xml = '<base/>'
    const { emitter, onChange } = setup(() => xml)
    emitter.setBaseline('<base/>')
    emitter.notify('execute')
    await vi.advanceTimersByTimeAsync(400)
    expect(onChange).not.toHaveBeenCalled()
    xml = '<changed/>'
    emitter.notify('execute')
    await vi.advanceTimersByTimeAsync(400)
    emitter.notify('execute')
    await vi.advanceTimersByTimeAsync(400)
    expect(onChange).toHaveBeenCalledTimes(1)
  })

  it('flush выдаёт отложенную правку сразу (перед размонтированием)', async () => {
    const { emitter, onChange } = setup(() => '<flushed/>')
    emitter.notify('execute')
    expect(emitter.hasPending()).toBe(true)
    await emitter.flush()
    expect(onChange).toHaveBeenCalledWith('<flushed/>')
    expect(emitter.hasPending()).toBe(false)
    await emitter.flush()
    expect(onChange).toHaveBeenCalledTimes(1)
  })

  it('cancel и новая база отбрасывают устаревшую сериализацию', async () => {
    let resolve: (xml: string) => void = () => {}
    const onChange = vi.fn()
    const emitter = createChangeEmitter({
      delay: 400,
      serialize: () => new Promise<string>((done) => (resolve = done)),
      onChange,
    })
    emitter.notify('execute')
    await vi.advanceTimersByTimeAsync(400)
    emitter.setBaseline('<imported/>')
    resolve('<stale/>')
    await vi.runAllTimersAsync()
    expect(onChange).not.toHaveBeenCalled()

    emitter.notify('execute')
    emitter.cancel()
    await vi.advanceTimersByTimeAsync(1000)
    expect(onChange).not.toHaveBeenCalled()
  })

  it('ошибку сериализации отдаёт в onError', async () => {
    const onError = vi.fn()
    const emitter = createChangeEmitter({
      delay: 10,
      serialize: () => Promise.reject(new Error('boom')),
      onChange: vi.fn(),
      onError,
    })
    emitter.notify()
    await vi.advanceTimersByTimeAsync(10)
    expect(onError).toHaveBeenCalledWith(expect.objectContaining({ message: 'boom' }))
  })
})
