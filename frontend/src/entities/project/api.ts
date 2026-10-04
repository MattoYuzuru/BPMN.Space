import {
  type InfiniteData,
  infiniteQueryOptions,
  type QueryClient,
  queryOptions,
  useMutation,
  useQueryClient,
} from '@tanstack/react-query'
import { api, errorMessage, type Schemas, unwrap } from '@/shared/api/client'
import { toast } from '@/shared/ui'

export type Project = Schemas['Project']
export type ProjectDetail = Schemas['ProjectDetail']
export type ProjectPage = Schemas['ProjectPage']

/** Размер страницы списка проектов: две-три «высоты экрана» карточек на широком мониторе. */
export const PROJECTS_PAGE_SIZE = 12

/**
 * Ключи запросов. Иерархия позволяет инвалидировать пачкой:
 * `projectKeys.all` — всё о проектах, `projectKeys.detail(id)` — проект с версиями.
 */
export const projectKeys = {
  all: ['projects'] as const,
  lists: () => [...projectKeys.all, 'list'] as const,
  list: (q: string) => [...projectKeys.lists(), { q }] as const,
  details: () => [...projectKeys.all, 'detail'] as const,
  detail: (id: string) => [...projectKeys.details(), id] as const,
}

/** Источник ещё разбирается — проект нужно опрашивать, пока он не станет ready/failed. */
export function hasProcessingSources(project: ProjectDetail | undefined): boolean {
  return Boolean(project?.sources.some((source) => source.status === 'processing'))
}

export function projectsInfiniteOptions(q: string) {
  return infiniteQueryOptions({
    queryKey: projectKeys.list(q),
    queryFn: async ({ pageParam, signal }) =>
      unwrap(
        await api.GET('/api/v1/projects', {
          params: { query: { cursor: pageParam, limit: PROJECTS_PAGE_SIZE, q: q || undefined } },
          signal,
        }),
      ),
    initialPageParam: null as string | null,
    getNextPageParam: (last) => last.next_cursor,
  })
}

export function projectQueryOptions(projectId: string) {
  return queryOptions({
    queryKey: projectKeys.detail(projectId),
    queryFn: async ({ signal }) =>
      unwrap(
        await api.GET('/api/v1/projects/{project_id}', {
          params: { path: { project_id: projectId } },
          signal,
        }),
      ),
    // Опрос только пока есть источники в обработке; остальное обновляют SSE и фокус окна.
    refetchInterval: (query) => (hasProcessingSources(query.state.data) ? 1500 : false),
  })
}

/** Применить изменение к проекту во всех загруженных страницах списка. */
export function patchProjectInLists(
  client: QueryClient,
  projectId: string,
  patch: (project: Project) => Project | null,
) {
  client.setQueriesData<InfiniteData<ProjectPage, string | null>>(
    { queryKey: projectKeys.lists() },
    (data) => {
      if (!data) return data
      return {
        ...data,
        pages: data.pages.map((page) => {
          const items = page.items.flatMap((project) => {
            if (project.id !== projectId) return [project]
            const next = patch(project)
            return next ? [next] : []
          })
          const removed = page.items.length - items.length
          return { ...page, items, total: page.total - removed }
        }),
      }
    },
  )
}

/** Создать пустой проект (без уведомлений и кэша — для составных сценариев). */
export async function createProject(body: Schemas['ProjectCreate']) {
  return unwrap(await api.POST('/api/v1/projects', { body }))
}

export function useCreateProject() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: createProject,
    onSuccess: () => client.invalidateQueries({ queryKey: projectKeys.lists() }),
  })
}

export function useCreateProjectFromExample() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: async (exampleId: string) =>
      unwrap(await api.POST('/api/v1/projects/from-example', { body: { example_id: exampleId } })),
    onSuccess: () => client.invalidateQueries({ queryKey: projectKeys.lists() }),
  })
}

/** Переименование с оптимистичным обновлением: шапка и список меняются сразу, при ошибке — откат. */
export function useRenameProject(projectId: string) {
  const client = useQueryClient()
  const key = projectKeys.detail(projectId)
  return useMutation({
    mutationFn: async (title: string) =>
      unwrap(
        await api.PATCH('/api/v1/projects/{project_id}', {
          params: { path: { project_id: projectId } },
          body: { title },
        }),
      ),
    onMutate: async (title) => {
      await client.cancelQueries({ queryKey: key })
      const previous = client.getQueryData<ProjectDetail>(key)
      client.setQueryData<ProjectDetail>(key, (data) => data && { ...data, title })
      patchProjectInLists(client, projectId, (project) => ({ ...project, title }))
      return { previous }
    },
    onError: (error, _title, context) => {
      if (context?.previous) client.setQueryData(key, context.previous)
      void client.invalidateQueries({ queryKey: projectKeys.lists() })
      toast.error('Не удалось переименовать проект', { description: errorMessage(error) })
    },
    onSettled: () => client.invalidateQueries({ queryKey: projectKeys.lists() }),
  })
}

/** Удаление: карточка исчезает из списка сразу, при ошибке (например, идёт прогон) — возвращается. */
export function useDeleteProject() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: async (projectId: string) =>
      unwrap(
        await api.DELETE('/api/v1/projects/{project_id}', {
          params: { path: { project_id: projectId } },
        }),
      ),
    onMutate: async (projectId) => {
      await client.cancelQueries({ queryKey: projectKeys.lists() })
      const snapshot = client.getQueriesData({ queryKey: projectKeys.lists() })
      patchProjectInLists(client, projectId, () => null)
      return { snapshot }
    },
    onError: (error, _id, context) => {
      for (const [key, data] of context?.snapshot ?? []) client.setQueryData(key, data)
      toast.error('Не удалось удалить проект', { description: errorMessage(error) })
    },
    onSuccess: (_data, projectId) => {
      client.removeQueries({ queryKey: projectKeys.detail(projectId) })
      toast.success('Проект удалён')
    },
    onSettled: () => client.invalidateQueries({ queryKey: projectKeys.lists() }),
  })
}
