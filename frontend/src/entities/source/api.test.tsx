import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, renderHook, waitFor } from '@testing-library/react'
import type { ReactNode } from 'react'
import { type ProjectDetail, projectKeys } from '@/entities/project'
import { stubApi } from '@/test/api-stub'
import { sampleKeys, useAddSampleSource, useDeleteSource, useSamples, useUpdateSource } from './api'
import type { Sample, Source } from './model'

const toastSuccess = vi.fn()
const toastError = vi.fn()
vi.mock('@/shared/ui', async (original) => ({
  ...(await original<typeof import('@/shared/ui')>()),
  toast: Object.assign(vi.fn(), {
    success: (...args: unknown[]) => toastSuccess(...args),
    error: (...args: unknown[]) => toastError(...args),
  }),
}))

const samples: Sample[] = [
  {
    id: 'tp861-meeting-note',
    title: 'Записка со встречи — техприсоединение.docx',
    kind: 'document',
    format: 'docx',
    size_bytes: 1764,
    tour: true,
  },
  {
    id: 'voice-request-approval',
    title: 'Голосовая заметка — согласование заявки',
    kind: 'voice',
    format: 'voice',
    size_bytes: 987,
    tour: false,
  },
]

const created: Source = {
  id: 's-1',
  project_id: 'p-1',
  kind: 'file',
  title: 'Записка со встречи — техприсоединение.docx',
  content: '',
  status: 'processing',
  active: true,
  created_at: '2026-10-04T10:00:00Z',
  origin: 'user',
  trust: 'primary',
  edited_by_human: false,
}

function setup() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  client.setQueryData(projectKeys.detail('p-1'), {
    id: 'p-1',
    sources: [],
  } as unknown as ProjectDetail)
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  )
  return { client, wrapper }
}

afterEach(() => {
  vi.unstubAllGlobals()
  toastSuccess.mockReset()
  toastError.mockReset()
})

describe('useSamples', () => {
  it('загружает список один раз и держит его в кэше', async () => {
    const calls = stubApi({ 'GET /api/v1/samples': { body: samples } })
    const { client, wrapper } = setup()
    const { result } = renderHook(() => useSamples(), { wrapper })
    await waitFor(() => expect(result.current.data).toEqual(samples))
    expect(client.getQueryData(sampleKeys.all)).toEqual(samples)
    renderHook(() => useSamples(), { wrapper })
    await act(async () => {})
    expect(calls).toHaveLength(1)
  })
})

describe('useAddSampleSource', () => {
  it('добавляет материал источником и сразу кладёт его в проект', async () => {
    const calls = stubApi({
      'POST /api/v1/projects/p-1/sources/sample': { status: 201, body: created },
    })
    const { client, wrapper } = setup()
    const { result } = renderHook(() => useAddSampleSource('p-1'), { wrapper })
    await act(async () => {
      await result.current.mutateAsync('tp861-meeting-note')
    })
    expect(calls[0]?.body).toEqual({ sample_id: 'tp861-meeting-note' })
    expect(client.getQueryData<ProjectDetail>(projectKeys.detail('p-1'))?.sources).toEqual([
      created,
    ])
    expect(toastSuccess).toHaveBeenCalledWith('Источник добавлен', { description: created.title })
  })

  it('ошибка — уведомление с текстом сервера', async () => {
    stubApi({
      'POST /api/v1/projects/p-1/sources/sample': {
        status: 404,
        body: { detail: 'Учебный материал не найден' },
      },
    })
    const { wrapper } = setup()
    const { result } = renderHook(() => useAddSampleSource('p-1'), { wrapper })
    await act(async () => {
      await result.current.mutateAsync('нет').catch(() => undefined)
    })
    expect(toastError).toHaveBeenCalledWith('Источник не добавлен', {
      description: 'Учебный материал не найден',
      duration: 8000,
    })
  })
})

describe('каскады дерева в кэше', () => {
  const at = '2026-11-04T10:00:00Z'
  const node = (id: string, parent?: string): Source => ({
    id,
    project_id: 'p-1',
    kind: parent ? 'text' : 'file',
    title: id,
    content: parent ? '[00:00] Реплика.' : '',
    status: 'ready',
    active: true,
    created_at: at,
    origin: parent ? 'derived' : 'user',
    trust: parent ? 'extracted' : 'primary',
    edited_by_human: false,
    parent_id: parent,
  })
  const tree = [node('rec'), node('tr', 'rec'), node('sub', 'tr'), node('txt')]

  function seeded() {
    const ctx = setup()
    ctx.client.setQueryData(projectKeys.detail('p-1'), {
      id: 'p-1',
      sources: tree,
    } as unknown as ProjectDetail)
    return ctx
  }
  const cached = (client: QueryClient) =>
    client.getQueryData<ProjectDetail>(projectKeys.detail('p-1'))?.sources ?? []

  it('удаление записи сразу убирает её производные', async () => {
    stubApi({ 'DELETE /api/v1/sources/rec': { status: 204 } })
    const { client, wrapper } = seeded()
    const { result } = renderHook(() => useDeleteSource('p-1'), { wrapper })
    await act(async () => {
      await result.current.mutateAsync('rec')
    })
    expect(cached(client).map((source) => source.id)).toEqual(['txt'])
  })

  it('выключение записи сразу выключает производные, ошибка откатывает всё', async () => {
    stubApi({
      'PATCH /api/v1/sources/rec': { status: 200, body: { ...tree[0], active: false } },
    })
    const { client, wrapper } = seeded()
    const { result } = renderHook(() => useUpdateSource('p-1'), { wrapper })
    await act(async () => {
      await result.current.mutateAsync({ id: 'rec', active: false })
    })
    expect(cached(client).map((source) => [source.id, source.active])).toEqual([
      ['rec', false],
      ['tr', false],
      ['sub', false],
      ['txt', true],
    ])

    stubApi({ 'PATCH /api/v1/sources/rec': { status: 422, body: { detail: 'Нельзя' } } })
    await act(async () => {
      await result.current.mutateAsync({ id: 'rec', active: true }).catch(() => undefined)
    })
    expect(cached(client).every((source) => source.id === 'txt' || !source.active)).toBe(true)
  })

  it('правка названия не трогает производные', async () => {
    stubApi({
      'PATCH /api/v1/sources/rec': { status: 200, body: { ...tree[0], title: 'Новая' } },
    })
    const { client, wrapper } = seeded()
    const { result } = renderHook(() => useUpdateSource('p-1'), { wrapper })
    await act(async () => {
      await result.current.mutateAsync({ id: 'rec', title: 'Новая' })
    })
    const derived = cached(client).filter((source) => source.parent_id)
    expect(derived.every((source) => source.active)).toBe(true)
  })
})
