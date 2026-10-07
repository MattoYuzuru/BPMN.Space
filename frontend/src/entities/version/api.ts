import {
  type QueryKey,
  queryOptions,
  type UseQueryOptions,
  useMutation,
  useQueryClient,
} from '@tanstack/react-query'
import { type ProjectDetail, projectKeys } from '@/entities/project'
import { ApiError, api, errorMessage, unwrap, versionXmlUrl } from '@/shared/api/client'
import { toast } from '@/shared/ui'
import { type Version, type VersionDetail, versionLabel } from './model'

export const versionKeys = {
  /** Список версий — внутри ключа проекта: инвалидация проекта обновляет и его. */
  list: (projectId: string) => [...projectKeys.detail(projectId), 'versions'] as const,
  /** Версия с XML неизменна — кэшируется навсегда. */
  detail: (versionId: string) => ['versions', versionId] as const,
}

export function versionsQueryOptions(projectId: string) {
  return queryOptions<Version[], Error, Version[], QueryKey>({
    queryKey: versionKeys.list(projectId),
    queryFn: async ({ signal }) =>
      unwrap(
        await api.GET('/api/v1/projects/{project_id}/versions', {
          params: { path: { project_id: projectId } },
          signal,
        }),
      ),
  })
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
 * Ручная правка схемы -> новая версия `manual`. XML уже есть у редактора, поэтому кладём его
 * в кэш новой версии сразу: редактор не перечитывает схему и не теряет историю отмены.
 */
export interface SaveDiagramInput {
  xml: string
  baseVersionId: string | null
}

export function useSaveDiagram(projectId: string) {
  const client = useQueryClient()
  const mutation = useMutation({
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
              versions:
                project.counts.versions +
                (version.id === baseVersionId || version.id === project.latest_version?.id ? 0 : 1),
            },
          },
      )
      client.setQueryData<Version[]>(versionKeys.list(projectId), (list) =>
        list ? [version, ...list.filter((item) => item.id !== version.id)] : list,
      )
      toast.success('Схема сохранена', { id: 'diagram-save', description: versionLabel(version) })
    },
    onError: (error, input) => {
      if (error instanceof ApiError && error.code === 'stale_version') return
      toast.error('Правка схемы не сохранена', {
        id: 'diagram-save',
        description: errorMessage(error),
        action: { label: 'Повторить', onClick: () => mutation.mutate(input) },
        duration: 10_000,
      })
    },
    onSettled: () => client.invalidateQueries({ queryKey: versionKeys.list(projectId) }),
  })
  return mutation
}

/**
 * Откуда рабочее место берёт версии схемы. У проекта аккаунта это обычные запросы по id версии;
 * у публичной ссылки — свои (`entities/share`), потому что по ней открыта только последняя
 * версия и только через путь ссылки. Виджеты не знают, какой источник им достался.
 */
export interface VersionSource {
  /** Версия с XML. */
  detail: (versionId: string) => UseQueryOptions<VersionDetail, Error, VersionDetail, QueryKey>
  /** Список версий проекта (новые первыми). */
  list: (projectId: string) => UseQueryOptions<Version[], Error, Version[], QueryKey>
  /** Адрес скачивания файла .bpmn. */
  xmlUrl: (versionId: string) => string
  /** Есть ли история: выбор старых версий и их просмотр. */
  history: boolean
}

export const projectVersionSource: VersionSource = {
  detail: versionDetailOptions,
  list: versionsQueryOptions,
  xmlUrl: versionXmlUrl,
  history: true,
}
