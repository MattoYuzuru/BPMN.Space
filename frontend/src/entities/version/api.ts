import {
  type InfiniteData,
  infiniteQueryOptions,
  type QueryClient,
  type QueryKey,
  queryOptions,
  type UseInfiniteQueryOptions,
  type UseQueryOptions,
  useMutation,
  useQueryClient,
} from '@tanstack/react-query'
import { type ProjectDetail, projectKeys } from '@/entities/project'
import { api, unwrap, versionXmlUrl } from '@/shared/api/client'
import {
  toSummary,
  upsertVersion,
  type Version,
  type VersionDetail,
  type VersionPage,
  type VersionSummary,
} from './model'

/** Размер страницы истории и короткого списка в шапке. */
export const HISTORY_PAGE_SIZE = 30
export const RECENT_VERSIONS = 6

export const versionKeys = {
  /**
   * Все списки версий проекта. Отдельно от ключа проекта: инвалидация проекта (прогон, событие
   * комнаты) не должна перечитывать историю.
   */
  all: (projectId: string) => ['project-versions', projectId] as const,
  /** Несколько последних версий (шапка, выбор базы сравнения). */
  list: (projectId: string, limit: number = RECENT_VERSIONS) =>
    [...versionKeys.all(projectId), 'list', limit] as const,
  /** История страницами для боковой панели. */
  pages: (projectId: string) => [...versionKeys.all(projectId), 'pages'] as const,
  /** Версия с XML неизменна — кэшируется навсегда. */
  detail: (versionId: string) => ['versions', versionId] as const,
}

async function fetchPage(
  projectId: string,
  limit: number,
  before: number | undefined,
  signal: AbortSignal,
): Promise<VersionPage> {
  return unwrap(
    await api.GET('/api/v1/projects/{project_id}/versions', {
      params: { path: { project_id: projectId }, query: { limit, before } },
      signal,
    }),
  )
}

export function versionsQueryOptions(projectId: string, limit: number = RECENT_VERSIONS) {
  return queryOptions<VersionSummary[], Error, VersionSummary[], QueryKey>({
    queryKey: versionKeys.list(projectId, limit),
    queryFn: async ({ signal }) => (await fetchPage(projectId, limit, undefined, signal)).items,
  })
}

export type VersionPagesData = InfiniteData<VersionPage, number | undefined>

export function versionPagesOptions(projectId: string) {
  return infiniteQueryOptions<VersionPage, Error, VersionPagesData, QueryKey, number | undefined>({
    queryKey: versionKeys.pages(projectId),
    initialPageParam: undefined,
    queryFn: ({ signal, pageParam }) => fetchPage(projectId, HISTORY_PAGE_SIZE, pageParam, signal),
    getNextPageParam: (last) => last.next_before ?? undefined,
  })
}

/**
 * Кладёт версию (сохранённую здесь, пришедшую из потока прогона или события комнаты) во все
 * загруженные списки истории без перечитывания: слитая сессия правок заменяет запись с тем же
 * номером, а повторная доставка не создаёт дубль.
 */
export function cacheVersion(client: QueryClient, projectId: string, version: VersionSummary) {
  const summary = toSummary(version)
  client.setQueriesData<VersionSummary[] | VersionPagesData>(
    { queryKey: versionKeys.all(projectId) },
    (data) => {
      if (!data) return data
      if (Array.isArray(data)) return upsertVersion(data, summary)
      const [first, ...rest] = data.pages
      if (!first) return data
      return { ...data, pages: [{ ...first, items: upsertVersion(first.items, summary) }, ...rest] }
    },
  )
}

export function versionDetailOptions(versionId: string) {
  return queryOptions<VersionDetail, Error, VersionDetail, QueryKey>({
    queryKey: versionKeys.detail(versionId),
    queryFn: async ({ signal }) =>
      unwrap(
        await api.GET('/api/v1/versions/{version_id}', {
          params: { path: { version_id: versionId } },
          signal,
        }),
      ),
    staleTime: Number.POSITIVE_INFINITY,
    gcTime: 30 * 60_000,
  })
}

/**
 * Ручная правка схемы -> версия `manual` (автосохранения одного автора сервер сливает в одну
 * версию). XML уже есть у редактора, поэтому кладём его в кэш версии сразу: редактор не
 * перечитывает схему и не теряет историю отмены. Сообщения об ошибках показывает вызывающий:
 * ему же нужен «Повторить» через очередь сохранений.
 */
export interface SaveDiagramInput {
  xml: string
  baseVersionId: string | null
}

export function useSaveDiagram(projectId: string) {
  const client = useQueryClient()
  return useMutation({
    mutationFn: async ({ xml, baseVersionId }: SaveDiagramInput) =>
      unwrap(
        await api.PUT('/api/v1/projects/{project_id}/diagram', {
          params: { path: { project_id: projectId } },
          body: { xml, base_version_id: baseVersionId },
        }),
      ),
    onSuccess: (version: Version, { xml, baseVersionId }) => {
      client.setQueryData<VersionDetail>(versionKeys.detail(version.id), { ...version, xml })
      client.setQueryData<ProjectDetail>(
        projectKeys.detail(projectId),
        (project) =>
          project && {
            ...project,
            latest_version: version,
            counts: {
              ...project.counts,
              // Слитая сессия сохраняет номер: версий не прибавляется.
              versions:
                project.counts.versions +
                (version.id === baseVersionId ||
                version.number <= (project.latest_version?.number ?? 0)
                  ? 0
                  : 1),
            },
          },
      )
      cacheVersion(client, projectId, version)
    },
  })
}

/** Закрепить версию как контрольную точку («Сохранить версию»); имя необязательно. */
export function useCheckpointVersion(projectId: string) {
  const client = useQueryClient()
  return useMutation({
    mutationFn: async ({ versionId, label }: { versionId: string; label?: string }) =>
      unwrap(
        await api.POST('/api/v1/projects/{project_id}/versions/{version_id}/checkpoint', {
          params: { path: { project_id: projectId, version_id: versionId } },
          body: { label: label?.trim() || null },
        }),
      ),
    onSuccess: (version) => {
      client.setQueryData<ProjectDetail>(
        projectKeys.detail(projectId),
        (project) =>
          project && {
            ...project,
            latest_version:
              project.latest_version?.id === version.id ? version : project.latest_version,
          },
      )
      cacheVersion(client, projectId, version)
    },
  })
}

/**
 * Откуда рабочее место берёт версии схемы. У проекта аккаунта это обычные запросы по id версии;
 * у публичной ссылки — свои (`entities/share`), потому что по ней открыта только последняя
 * версия и только через путь ссылки. Виджеты не знают, какой источник им достался.
 */
export interface VersionSource {
  /** Версия с XML. */
  detail: (versionId: string) => UseQueryOptions<VersionDetail, Error, VersionDetail, QueryKey>
  /** Несколько последних версий проекта (новые первыми). */
  list: (
    projectId: string,
    limit?: number,
  ) => UseQueryOptions<VersionSummary[], Error, VersionSummary[], QueryKey>
  /** Вся история страницами (боковая панель). */
  pages: (
    projectId: string,
  ) => UseInfiniteQueryOptions<VersionPage, Error, VersionPagesData, QueryKey, number | undefined>
  /** Адрес скачивания файла .bpmn. */
  xmlUrl: (versionId: string) => string
  /** Есть ли история: выбор старых версий и их просмотр. */
  history: boolean
}

export const projectVersionSource: VersionSource = {
  detail: versionDetailOptions,
  list: versionsQueryOptions,
  pages: versionPagesOptions,
  xmlUrl: versionXmlUrl,
  history: true,
}
