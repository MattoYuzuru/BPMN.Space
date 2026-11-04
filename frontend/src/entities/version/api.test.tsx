import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, renderHook } from '@testing-library/react'
import type { ReactNode } from 'react'
import { type ProjectDetail, projectKeys } from '@/entities/project'
import { stubApi } from '@/test/api-stub'
import { useSaveDiagram, versionKeys } from './api'
import { toSummary, type Version, type VersionDetail, type VersionSummary } from './model'

const initial: Version = {
  id: 'v-1',
  project_id: 'p-1',
  number: 1,
  origin: 'manual',
  created_at: '2026-10-07T10:00:00Z',
  diff: { added: 0, changed: 0, removed: 0 },
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
}

function setup(saved: Version) {
  stubApi({ 'PUT /api/v1/projects/p-1/diagram': { status: 201, body: saved } })
  const client = new QueryClient({ defaultOptions: { mutations: { retry: false } } })
  const project = {
    id: 'p-1',
    latest_version: initial,
    counts: { versions: 1 },
  } as unknown as ProjectDetail
  client.setQueryData(projectKeys.detail('p-1'), project)
  client.setQueryData(versionKeys.list('p-1'), [initial])
  client.setQueryData(versionKeys.pages('p-1'), {
    pages: [{ items: [initial], next_before: null }],
    pageParams: [undefined],
  })
  vi.spyOn(client, 'invalidateQueries').mockResolvedValue()
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  )
  const hook = renderHook(() => useSaveDiagram('p-1'), { wrapper })
  return { ...hook, client }
}

afterEach(() => {
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

it('идентичное сохранение возвращает прежнюю версию и не увеличивает счётчик истории', async () => {
  const { result, client } = setup(initial)
  for (let attempt = 0; attempt < 3; attempt += 1) {
    await act(async () => {
      await result.current.mutateAsync({ xml: '<same/>', baseVersionId: initial.id })
    })
    expect(client.getQueryData<ProjectDetail>(projectKeys.detail('p-1'))?.counts.versions).toBe(1)
    expect(client.getQueryData<VersionSummary[]>(versionKeys.list('p-1'))).toEqual([
      toSummary(initial),
    ])
  }
})

it('новая версия увеличивает счётчик и получает текущий XML в кэше detail', async () => {
  const saved = { ...initial, id: 'v-2', number: 2 }
  const { result, client } = setup(saved)
  await act(async () => {
    await result.current.mutateAsync({ xml: '<changed/>', baseVersionId: initial.id })
  })
  expect(client.getQueryData<ProjectDetail>(projectKeys.detail('p-1'))?.counts.versions).toBe(2)
  expect(
    client.getQueryData<VersionSummary[]>(versionKeys.list('p-1'))?.map((item) => item.id),
  ).toEqual(['v-2', 'v-1'])
  expect(client.getQueryData<VersionDetail>(versionKeys.detail(saved.id))?.xml).toBe('<changed/>')
})

it('ответ уже учтённой новой версии не увеличивает счётчик повторно', async () => {
  const saved = { ...initial, id: 'v-2', number: 2 }
  const { result, client } = setup(saved)
  client.setQueryData<ProjectDetail>(
    projectKeys.detail('p-1'),
    (project) =>
      project && {
        ...project,
        latest_version: saved,
        counts: { ...project.counts, versions: 2 },
      },
  )
  await act(async () => {
    await result.current.mutateAsync({ xml: '<changed/>', baseVersionId: initial.id })
  })
  expect(client.getQueryData<ProjectDetail>(projectKeys.detail('p-1'))?.counts.versions).toBe(2)
})

it('слитая сессия правок (тот же номер, новый id) заменяет запись, а не добавляет', async () => {
  const merged = { ...initial, id: 'v-1b', saved_count: 2 }
  const { result, client } = setup(merged)
  await act(async () => {
    await result.current.mutateAsync({ xml: '<merged/>', baseVersionId: initial.id })
  })
  expect(client.getQueryData<ProjectDetail>(projectKeys.detail('p-1'))?.counts.versions).toBe(1)
  expect(client.getQueryData<VersionSummary[]>(versionKeys.list('p-1'))).toEqual([
    toSummary(merged),
  ])
  const pages = client.getQueryData<{ pages: { items: VersionSummary[] }[] }>(
    versionKeys.pages('p-1'),
  )
  expect(pages?.pages[0]?.items).toEqual([toSummary(merged)])
})

it('сохранение не перечитывает список версий и не показывает тост успеха', async () => {
  const saved = { ...initial, id: 'v-2', number: 2 }
  const { result, client } = setup(saved)
  await act(async () => {
    await result.current.mutateAsync({ xml: '<changed/>', baseVersionId: initial.id })
  })
  expect(client.invalidateQueries).not.toHaveBeenCalled()
})
