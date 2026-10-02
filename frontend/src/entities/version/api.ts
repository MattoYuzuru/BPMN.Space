import { queryOptions, useMutation, useQueryClient } from '@tanstack/react-query'
import { type ProjectDetail, projectKeys } from '@/entities/project'
import { api, errorMessage, unwrap } from '@/shared/api/client'
import { toast } from '@/shared/ui'
import { type Version, type VersionDetail, versionLabel } from './model'

export const versionKeys = {
  /** Список версий — внутри ключа проекта: инвалидация проекта обновляет и его. */
  list: (projectId: string) => [...projectKeys.detail(projectId), 'versions'] as const,
  /** Версия с XML неизменна — кэшируется навсегда. */
  detail: (versionId: string) => ['versions', versionId] as const,
}

export function versionsQueryOptions(projectId: string) {
  return queryOptions({
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
  return queryOptions({
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
export function useSaveDiagram(projectId: string) {
  const client = useQueryClient()
  const mutation = useMutation({
    mutationFn: async (xml: string) =>
      unwrap(
        await api.PUT('/api/v1/projects/{project_id}/diagram', {
          params: { path: { project_id: projectId } },
          body: { xml },
        }),
      ),
    onSuccess: (version: Version, xml) => {
      client.setQueryData<VersionDetail>(versionKeys.detail(version.id), { ...version, xml })
      client.setQueryData<ProjectDetail>(
        projectKeys.detail(projectId),
        (project) =>
          project && {
            ...project,
            latest_version: version,
            counts: { ...project.counts, versions: project.counts.versions + 1 },
          },
      )
      client.setQueryData<Version[]>(versionKeys.list(projectId), (list) =>
        list ? [version, ...list.filter((item) => item.id !== version.id)] : list,
      )
      toast.success('Схема сохранена', { id: 'diagram-save', description: versionLabel(version) })
    },
    onError: (error, xml) =>
      toast.error('Правка схемы не сохранена', {
        id: 'diagram-save',
        description: errorMessage(error),
        action: { label: 'Повторить', onClick: () => mutation.mutate(xml) },
        duration: 10_000,
      }),
    onSettled: () => client.invalidateQueries({ queryKey: versionKeys.list(projectId) }),
  })
  return mutation
}
