import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, renderHook, waitFor } from '@testing-library/react'
import type { ReactNode } from 'react'
import { type ProjectDetail, projectKeys } from '@/entities/project'
import { stubApi } from '@/test/api-stub'
import { sampleKeys, useAddSampleSource, useSamples } from './api'
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
