import { type InfiniteData, QueryClient } from '@tanstack/react-query'
import { type Project, type ProjectPage, patchProjectInLists, projectKeys } from './api'

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
