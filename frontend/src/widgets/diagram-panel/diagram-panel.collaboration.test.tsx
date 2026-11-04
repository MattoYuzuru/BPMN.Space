import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, fireEvent, render, screen } from '@testing-library/react'
import type { ReactNode } from 'react'
import { type ProjectDetail, projectKeys } from '@/entities/project'
import { projectVersionSource, type VersionDetail, versionKeys } from '@/entities/version'
import { ApiError } from '@/shared/api/client'
import { toast } from '@/shared/ui'
import type { DiagramEditorHandle } from '@/widgets/diagram-editor'
import { type WorkspaceApi, WorkspaceContext } from '@/widgets/workspace/model'
import { DiagramPanel } from './diagram-panel'

type TransportEvent = { type: string; [key: string]: unknown }
const transport = vi.hoisted(() => {
  const listeners = new Set<(event: TransportEvent) => void>()
  return {
    listeners,
    /** Присваивание доставляет событие подписчикам, как сообщение сокета. */
    run: (callback: () => void) => callback(),
    set event(value: TransportEvent | null) {
      if (!value) return
      this.run(() => {
        for (const listener of [...listeners]) listener(value)
      })
    },
    enabledArgs: [] as unknown[],
    nextXml: '<draft/>',
    pendingTimer: 0,
    save: { isPending: false, isSuccess: false, mutateAsync: vi.fn() },
  }
})
vi.mock('@/features/project-collaboration/use-project-collaboration', () => ({
  useProjectCollaboration: (...args: unknown[]) => ({
    subscribe: (listener: (event: TransportEvent) => void) => {
      transport.enabledArgs = args
      transport.listeners.add(listener)
      return () => transport.listeners.delete(listener)
    },
    connected: false,
    localSessionId: 'tab-1',
    presence: {
      getSnapshot: () => [
        { session_id: 'tab-1', user_id: 'owner-1', display_name: 'owner@example.com' },
      ],
    },
    sendPresence: () => {},
  }),
}))
vi.mock('@/entities/version', async (original) => ({
  ...(await original<typeof import('@/entities/version')>()),
  useSaveDiagram: () => transport.save,
}))
vi.mock('@/entities/onboarding', () => ({ useReportOnboardingEvent: () => ({ mutate: () => {} }) }))
vi.mock('@/features/project-collaboration/collaborator-overlay', async (original) => ({
  ...(await original<typeof import('@/features/project-collaboration/collaborator-overlay')>()),
  CollaboratorOverlay: () => null,
}))
vi.mock('@/widgets/diagram-editor', () => ({
  LazyDiagramEditor: ({
    xml,
    onChange,
    onChangePending,
  }: {
    xml: string
    onChange: (xml: string) => void
    onChangePending?: (pending: boolean) => void
  }) => (
    <div>
      <pre data-testid="canvas-xml">{xml}</pre>
      <button type="button" onClick={() => onChange(transport.nextXml)}>
        Изменить схему
      </button>
      <button
        type="button"
        onClick={() => {
          onChangePending?.(true)
          transport.pendingTimer = window.setTimeout(() => {
            onChange(transport.nextXml)
            onChangePending?.(false)
          }, 400)
        }}
      >
        Изменить с задержкой XML
      </button>
    </div>
  ),
}))
vi.mock('@/widgets/run-progress/run-progress', () => ({ RunProgress: () => null }))
vi.mock('./diagram-toolbar', () => ({ DiagramToolbar: () => null }))
vi.mock('./element-inspector', () => ({ ElementInspector: () => null }))

transport.run = (callback) => act(callback)

const version = (id = 'v-1', xml = '<initial/>'): VersionDetail => ({
  id,
  project_id: 'p-1',
  number: id === 'v-1' ? 1 : 2,
  origin: 'manual',
  created_at: '2026-10-07T10:00:00Z',
  xml,
  diff: { added: 0, removed: 0, changed: 0 },
  report: { xsd_valid: true, lint: [], assumptions: [] },
  trace: {},
  lanes: [],
  label: null,
  checkpoint: false,
  session_started_at: '2026-10-07T10:00:00Z',
  updated_at: '2026-10-07T10:00:00Z',
  saved_count: 1,
  lint_count: 0,
  assumption_count: 0,
})

function mount() {
  const initial = version()
  const client = new QueryClient({ defaultOptions: { queries: { staleTime: Infinity } } })
  client.setQueryData(versionKeys.detail(initial.id), initial)
  client.setQueryData(versionKeys.pages('p-1'), {
    pages: [{ items: [initial], next_before: null }],
    pageParams: [undefined],
  })
  const invalidate = vi.spyOn(client, 'invalidateQueries').mockResolvedValue()
  const project = {
    id: 'p-1',
    title: 'Общая схема',
    latest_version: initial,
    status: 'ready',
    questions: [],
  } as unknown as ProjectDetail
  const workspace = {
    project,
    canEdit: true,
    versions: projectVersionSource,
    editorRef: { current: null },
  } as unknown as WorkspaceApi
  function wrapper({ children }: { children: ReactNode }) {
    return (
      <QueryClientProvider client={client}>
        <WorkspaceContext.Provider value={workspace}>{children}</WorkspaceContext.Provider>
      </QueryClientProvider>
    )
  }
  const view = render(<DiagramPanel />, { wrapper })
  return { ...view, client, workspace, invalidate, refresh: () => view.rerender(<DiagramPanel />) }
}

beforeEach(() => {
  vi.useFakeTimers()
  transport.listeners.clear()
  transport.nextXml = '<draft/>'
  transport.pendingTimer = 0
  transport.save.isPending = false
  transport.save.mutateAsync.mockReset()
  transport.save.mutateAsync.mockResolvedValue(version('v-own', '<draft/>'))
  vi.stubGlobal('URL', {
    createObjectURL: vi.fn(() => 'blob:draft'),
    revokeObjectURL: vi.fn(),
  })
  vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {})
})
afterEach(() => {
  vi.useRealTimers()
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

it.each(['owner@example.com', null])(
  'обновляет чистую вкладку после сохранения другой вкладкой с actor=%s',
  (actor) => {
    const panel = mount()
    transport.event = { type: 'diagram.version', version_id: 'v-2', actor }
    panel.refresh()
    expect(panel.invalidate).toHaveBeenCalledWith({ queryKey: projectKeys.detail('p-1') })
    expect(panel.invalidate).toHaveBeenCalledWith({ queryKey: versionKeys.all('p-1') })
  },
)

it('отмена черновика снимает отложенное сохранение до открытия серверной версии', async () => {
  const panel = mount()
  fireEvent.click(screen.getByRole('button', { name: 'Изменить схему' }))
  transport.event = { type: 'diagram.version', version_id: 'v-2', number: 2 }
  panel.refresh()
  fireEvent.click(screen.getByRole('button', { name: 'Открыть новую версию' }))
  await act(async () => vi.advanceTimersByTimeAsync(1600))
  expect(transport.save.mutateAsync).not.toHaveBeenCalled()
})

it('инвалидация проекта сохраняет несохранённый XML в холсте до явной синхронизации', () => {
  const panel = mount()
  fireEvent.click(screen.getByRole('button', { name: 'Изменить схему' }))
  transport.event = { type: 'diagram.version', version_id: 'v-2', number: 2 }
  panel.refresh()
  const remote = version('v-2', '<remote/>')
  panel.client.setQueryData(versionKeys.detail(remote.id), remote)
  panel.workspace.project = { ...panel.workspace.project, latest_version: remote }
  panel.refresh()
  expect(screen.getByTestId('canvas-xml')).toHaveTextContent('<draft/>')
  expect(screen.getByRole('button', { name: 'Открыть новую версию' })).toBeInTheDocument()
})

it('версия в первые 400 мс после команды не импортируется поверх ещё не выгруженной правки', async () => {
  const panel = mount()
  fireEvent.click(screen.getByRole('button', { name: 'Изменить с задержкой XML' }))
  await act(async () => vi.advanceTimersByTimeAsync(100))
  transport.event = { type: 'diagram.version', version_id: 'v-2', number: 2 }
  panel.refresh()
  expect(panel.invalidate).not.toHaveBeenCalled()
  expect(screen.getByRole('button', { name: 'Открыть новую версию' })).toBeInTheDocument()
  const remote = version('v-2', '<remote/>')
  panel.client.setQueryData(versionKeys.detail(remote.id), remote)
  panel.workspace.project = { ...panel.workspace.project, latest_version: remote }
  panel.refresh()
  expect(screen.getByTestId('canvas-xml')).toHaveTextContent('<initial/>')
  await act(async () => vi.advanceTimersByTimeAsync(300))
  panel.refresh()
  expect(screen.getByTestId('canvas-xml')).toHaveTextContent('<draft/>')
})

it('следующая правка в очереди не сохраняется после конфликта первой', async () => {
  mount()
  let reject: (error: Error) => void = () => {}
  transport.save.mutateAsync.mockImplementationOnce(
    () =>
      new Promise((_, fail) => {
        reject = fail
      }),
  )
  fireEvent.click(screen.getByRole('button', { name: 'Изменить схему' }))
  await act(async () => vi.advanceTimersByTimeAsync(1600))
  transport.nextXml = '<second-draft/>'
  fireEvent.click(screen.getByRole('button', { name: 'Изменить схему' }))
  await act(async () => vi.advanceTimersByTimeAsync(1600))
  await act(async () => {
    reject(new ApiError(409, 'Схема обновлена', { code: 'stale_version', headVersionId: 'v-2' }))
    await Promise.resolve()
  })
  expect(transport.save.mutateAsync).toHaveBeenCalledTimes(1)
  expect(screen.getByRole('button', { name: 'Открыть новую версию' })).toBeInTheDocument()
})

it('событие собственного сохранения до HTTP-ответа сверяется по id после ответа', async () => {
  const panel = mount()
  let resolve: (result: VersionDetail) => void = () => {}
  transport.save.mutateAsync.mockImplementationOnce(
    () =>
      new Promise<VersionDetail>((done) => {
        resolve = done
      }),
  )
  fireEvent.click(screen.getByRole('button', { name: 'Изменить схему' }))
  await act(async () => vi.advanceTimersByTimeAsync(1600))
  transport.save.isPending = true
  transport.event = { type: 'diagram.version', version_id: 'v-own', actor: 'owner@example.com' }
  panel.refresh()
  expect(screen.queryByRole('button', { name: 'Открыть новую версию' })).not.toBeInTheDocument()
  await act(async () => {
    resolve(version('v-own', '<draft/>'))
    await Promise.resolve()
  })
  transport.save.isPending = false
  panel.refresh()
  expect(screen.queryByRole('button', { name: 'Открыть новую версию' })).not.toBeInTheDocument()
  expect(panel.invalidate).not.toHaveBeenCalled()
})

it('собственная новая голова с ожидающим detail сохраняет тот же холст и текущий XML', async () => {
  vi.stubGlobal('fetch', () => new Promise(() => {}))
  const panel = mount()
  const canvas = screen.getByTestId('canvas-xml')
  // Как в `useSaveDiagram.onSuccess`: проект получает новую голову раньше, чем ответ дойдёт до панели.
  transport.save.mutateAsync.mockImplementationOnce(async () => {
    panel.workspace.project = {
      ...panel.workspace.project,
      latest_version: version('v-own', '<draft/>'),
    }
    return version('v-own', '<draft/>')
  })
  fireEvent.click(screen.getByRole('button', { name: 'Изменить схему' }))
  await act(async () => vi.advanceTimersByTimeAsync(1600))
  panel.refresh()
  expect(screen.getByTestId('canvas-xml')).toBe(canvas)
  expect(canvas).toHaveTextContent('<draft/>')
  await act(async () =>
    panel.client.setQueryData(versionKeys.detail('v-own'), version('v-own', '<draft/>')),
  )
  expect(screen.getByTestId('canvas-xml')).toBe(canvas)
  expect(canvas).toHaveTextContent('<draft/>')
})

it('открытие серверной версии в первые 400 мс скачивает текущий холст и отменяет отложенный XML', async () => {
  const panel = mount()
  const exportXml = vi.fn(async () => '<unemitted-draft/>')
  const cancelPendingChanges = vi.fn(() => window.clearTimeout(transport.pendingTimer))
  panel.workspace.editorRef.current = {
    exportXml,
    cancelPendingChanges,
  } as unknown as DiagramEditorHandle
  fireEvent.click(screen.getByRole('button', { name: 'Изменить с задержкой XML' }))
  transport.event = { type: 'diagram.version', version_id: 'v-2', number: 2 }
  panel.refresh()
  fireEvent.click(screen.getByRole('button', { name: 'Открыть новую версию' }))
  await act(async () => vi.advanceTimersByTimeAsync(1600))
  expect(exportXml).toHaveBeenCalledTimes(1)
  expect(cancelPendingChanges).toHaveBeenCalledTimes(1)
  expect(URL.createObjectURL).toHaveBeenCalledWith(expect.objectContaining({ size: 18 }))
  expect(transport.save.mutateAsync).not.toHaveBeenCalled()
})

it('сигнал ранней правки не обходит режим только просмотра', () => {
  const panel = mount()
  panel.workspace.canEdit = false
  panel.refresh()
  fireEvent.click(screen.getByRole('button', { name: 'Изменить с задержкой XML' }))
  transport.event = { type: 'diagram.version', version_id: 'v-2', number: 2 }
  panel.refresh()
  expect(panel.invalidate).toHaveBeenCalled()
  expect(screen.queryByRole('button', { name: 'Открыть новую версию' })).not.toBeInTheDocument()
  expect(transport.save.mutateAsync).not.toHaveBeenCalled()
})

it('«Повторить» после ошибки идёт через очередь: следующая правка основана на новой версии', async () => {
  const error = vi.spyOn(toast, 'error').mockReturnValue('t')
  mount()
  transport.save.mutateAsync.mockReset()
  transport.save.mutateAsync
    .mockRejectedValueOnce(new Error('Сеть недоступна'))
    .mockResolvedValue(version('v-own', '<draft/>'))
  fireEvent.click(screen.getByRole('button', { name: 'Изменить схему' }))
  await act(async () => vi.advanceTimersByTimeAsync(1600))
  const options = error.mock.calls[0]?.[1] as { action: { onClick: () => void } }
  await act(async () => options.action.onClick())
  expect(transport.save.mutateAsync).toHaveBeenLastCalledWith({
    xml: '<draft/>',
    baseVersionId: 'v-1',
  })

  transport.nextXml = '<second/>'
  fireEvent.click(screen.getByRole('button', { name: 'Изменить схему' }))
  await act(async () => vi.advanceTimersByTimeAsync(1600))
  expect(transport.save.mutateAsync).toHaveBeenLastCalledWith({
    xml: '<second/>',
    baseVersionId: 'v-own',
  })
  expect(screen.queryByText(/Коллега сохранил/)).not.toBeInTheDocument()
})

it('пока правка не сохранена, закрытие вкладки требует подтверждения', async () => {
  mount()
  fireEvent.click(screen.getByRole('button', { name: 'Изменить схему' }))
  const unsaved = new Event('beforeunload', { cancelable: true })
  window.dispatchEvent(unsaved)
  expect(unsaved.defaultPrevented).toBe(true)
  await act(async () => vi.advanceTimersByTimeAsync(0))
  const saved = new Event('beforeunload', { cancelable: true })
  window.dispatchEvent(saved)
  expect(saved.defaultPrevented).toBe(false)
})

it('два события в одном пакете обрабатываются оба', () => {
  const panel = mount()
  fireEvent.click(screen.getByRole('button', { name: 'Изменить схему' }))
  act(() => {
    for (const listener of [...transport.listeners]) {
      listener({ type: 'run.changed', status: 'succeeded', version_id: 'v-2', number: 2 })
      listener({ type: 'diagram.version', version_id: 'v-3', number: 3 })
    }
  })
  // Второе событие не затирает первое: баннер показывает последнюю версию, а не теряет её.
  expect(screen.getByText(/Коллега сохранил версию 3/)).toBeInTheDocument()
  expect(panel.invalidate).not.toHaveBeenCalled()
})

it('«Отменить мои правки» после подтверждения открывает версию коллеги без скачивания', async () => {
  const panel = mount()
  fireEvent.click(screen.getByRole('button', { name: 'Изменить схему' }))
  transport.event = { type: 'diagram.version', version_id: 'v-2', number: 2 }
  fireEvent.click(screen.getByRole('button', { name: 'Отменить мои правки' }))
  expect(screen.getByRole('alertdialog')).toBeInTheDocument()
  await act(async () => {
    fireEvent.click(screen.getByRole('button', { name: 'Отменить правки' }))
    await vi.advanceTimersByTimeAsync(1600)
  })
  expect(URL.createObjectURL).not.toHaveBeenCalled()
  expect(screen.queryByText(/Коллега сохранил/)).not.toBeInTheDocument()
  expect(transport.save.mutateAsync).not.toHaveBeenCalled()
  expect(panel.invalidate).toHaveBeenCalledWith({ queryKey: projectKeys.detail('p-1') })
})

it('скачивание черновика добавляет ссылку в документ и освобождает адрес позже', async () => {
  vi.useRealTimers()
  vi.useFakeTimers()
  const append = vi.spyOn(document.body, 'append')
  mount()
  fireEvent.click(screen.getByRole('button', { name: 'Изменить схему' }))
  transport.event = { type: 'diagram.version', version_id: 'v-2', number: 2 }
  await act(async () => {
    fireEvent.click(screen.getByRole('button', { name: 'Скачать черновик' }))
  })
  expect(append).toHaveBeenCalledWith(expect.any(HTMLAnchorElement))
  expect(URL.revokeObjectURL).not.toHaveBeenCalled()
  await act(async () => vi.advanceTimersByTimeAsync(1100))
  expect(URL.revokeObjectURL).toHaveBeenCalledWith('blob:draft')
})
