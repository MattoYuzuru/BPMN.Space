import { type InfiniteData, QueryClient } from '@tanstack/react-query'
import { stubApi } from '@/test/api-stub'
import {
  type Project,
  type ProjectPage,
  patchProjectInLists,
  projectKeys,
  projectsInfiniteOptions,
} from './api'

const project = (id: string, title = id) => ({ id, title }) as Project

describe('patchProjectInLists', () => {
  it('меняет и удаляет проект во всех страницах всех поисков', () => {
    const client = new QueryClient()
    const page = (items: Project[], total: number): ProjectPage => ({
      items,
      total,
      next_cursor: null,
    })
    client.setQueryData<InfiniteData<ProjectPage, string | null>>(projectKeys.list(''), {
      pages: [page([project('a'), project('b')], 3), page([project('c')], 3)],
      pageParams: [null, 'c1'],
    })
    client.setQueryData<InfiniteData<ProjectPage, string | null>>(projectKeys.list('b'), {
      pages: [page([project('b')], 1)],
      pageParams: [null],
    })

    patchProjectInLists(client, 'b', (item) => ({ ...item, title: 'Новое' }))
    const all = client.getQueryData<InfiniteData<ProjectPage>>(projectKeys.list(''))
    expect(all?.pages[0]?.items[1]?.title).toBe('Новое')
    expect(
      client.getQueryData<InfiniteData<ProjectPage>>(projectKeys.list('b'))?.pages[0]?.items[0]
        ?.title,
    ).toBe('Новое')

    patchProjectInLists(client, 'c', () => null)
    const after = client.getQueryData<InfiniteData<ProjectPage>>(projectKeys.list(''))
    expect(after?.pages[1]?.items).toEqual([])
    expect(after?.pages[1]?.total).toBe(2)
  })
})

describe('projectsInfiniteOptions и область списка', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('у каждой области свой ключ кэша: страницы «Мои» не смешиваются с «Общими»', () => {
    expect(projectKeys.list('', 'own')).not.toEqual(projectKeys.list('', 'shared'))
    expect(projectKeys.list('схема')).toEqual(projectKeys.list('схема', 'all'))
  })

  it('область и поиск уходят в запрос, «все» параметра не добавляет', async () => {
    const calls = stubApi({
      'GET /api/v1/projects': { body: { items: [], total: 0, next_cursor: null } },
    })
    const client = new QueryClient()
    await client.fetchInfiniteQuery(projectsInfiniteOptions('схема', 'shared'))
    await client.fetchInfiniteQuery(projectsInfiniteOptions('', 'all'))
    expect(calls[0]?.search.get('scope')).toBe('shared')
    expect(calls[0]?.search.get('q')).toBe('схема')
    expect(calls[1]?.search.has('scope')).toBe(false)
  })
})
