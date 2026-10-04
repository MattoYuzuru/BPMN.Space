import {
  type QueryKey,
  queryOptions,
  useMutation,
  useQuery,
  useQueryClient,
} from '@tanstack/react-query'
import { type ProjectDetail, projectKeys } from '@/entities/project'
import type { Version, VersionDetail, VersionSource } from '@/entities/version'
import { api, errorMessage, unwrap } from '@/shared/api/client'
import { toast } from '@/shared/ui'
import type { SharedProject, ShareRole } from './model'

/**
 * Ключи запросов. Ссылки и участники живут внутри проекта — его инвалидация обновляет и их;
 * публичный просмотр — отдельным корнем `shares`, токен только в оперативной памяти страницы.
 */
export const shareKeys = {
  links: (projectId: string) => [...projectKeys.detail(projectId), 'share-links'] as const,
  members: (projectId: string) => [...projectKeys.detail(projectId), 'members'] as const,
  shared: (token: string) => ['shares', token] as const,
}

export function shareLinksQueryOptions(projectId: string) {
  return queryOptions({
    queryKey: shareKeys.links(projectId),
    queryFn: async ({ signal }) =>
      unwrap(
        await api.GET('/api/v1/projects/{project_id}/share-links', {
          params: { path: { project_id: projectId } },
          signal,
        }),
      ),
    // Диалог открывают редко и на короткое время: свежие данные важнее кэша.
    staleTime: 0,
  })
}

export function projectMembersQueryOptions(projectId: string) {
  return queryOptions({
    queryKey: shareKeys.members(projectId),
    queryFn: async ({ signal }) =>
      unwrap(
        await api.GET('/api/v1/projects/{project_id}/members', {
          params: { path: { project_id: projectId } },
          signal,
        }),
      ),
    staleTime: 0,
  })
}

interface CreateLinkInput {
  role: ShareRole
  days: number
}

/** Создать ссылку. Ошибка — тост; секрет приходит в ответе один раз и в кэш не кладётся. */
export function useCreateShareLink(projectId: string) {
  const client = useQueryClient()
  return useMutation({
    mutationFn: async ({ role, days }: CreateLinkInput) =>
      unwrap(
        await api.POST('/api/v1/projects/{project_id}/share-links', {
          params: { path: { project_id: projectId } },
          body: { role, expires_in_days: days },
        }),
      ),
    onSuccess: () => client.invalidateQueries({ queryKey: shareKeys.links(projectId) }),
    onError: (error) =>
      toast.error('Не удалось создать ссылку', { description: errorMessage(error) }),
  })
}

/** Отозвать ссылку: она сразу исчезает из списка, при ошибке возвращается. */
export function useRevokeShareLink(projectId: string) {
  const client = useQueryClient()
  const key = shareKeys.links(projectId)
  return useMutation({
    mutationFn: async (linkId: string) =>
      unwrap(
        await api.DELETE('/api/v1/projects/{project_id}/share-links/{link_id}', {
          params: { path: { project_id: projectId, link_id: linkId } },
        }),
      ),
    onMutate: async (linkId) => {
      await client.cancelQueries({ queryKey: key })
      const previous = client.getQueryData(key)
      client.setQueryData<{ id: string }[]>(key, (links) =>
        links?.filter((link) => link.id !== linkId),
      )
      return { previous }
    },
    onError: (error, _id, context) => {
      if (context?.previous) client.setQueryData(key, context.previous)
      toast.error('Не удалось отозвать ссылку', { description: errorMessage(error) })
    },
    onSuccess: () => toast.success('Ссылка отозвана'),
    onSettled: () => client.invalidateQueries({ queryKey: key }),
  })
}

export function useRemoveMember(projectId: string) {
  const client = useQueryClient()
  const key = shareKeys.members(projectId)
  return useMutation({
    mutationFn: async (userId: string) =>
      unwrap(
        await api.DELETE('/api/v1/projects/{project_id}/members/{member_id}', {
          params: { path: { project_id: projectId, member_id: userId } },
        }),
      ),
    onMutate: async (userId) => {
      await client.cancelQueries({ queryKey: key })
      const previous = client.getQueryData(key)
      client.setQueryData<{ user_id: string }[]>(key, (members) =>
        members?.filter((member) => member.user_id !== userId),
      )
      return { previous }
    },
    onError: (error, _id, context) => {
      if (context?.previous) client.setQueryData(key, context.previous)
      toast.error('Не удалось убрать участника', { description: errorMessage(error) })
    },
    onSuccess: () => toast.success('Участник убран'),
    onSettled: () => client.invalidateQueries({ queryKey: key }),
  })
}

/**
 * Проект по ссылке. 401/404/410 — обычные состояния страницы, а не сбои, поэтому повторов нет.
 * Данные не стареют быстро: страницу открывают читать, а не следить за изменениями.
 */
export function sharedProjectQueryOptions(token: string) {
  return queryOptions({
    queryKey: shareKeys.shared(token),
    queryFn: async ({ signal }): Promise<SharedProject> =>
      unwrap(await api.GET('/api/v1/shares/{token}', { params: { path: { token } }, signal })),
    retry: false,
    staleTime: 60_000,
  })
}

/**
 * Источник версий для публичного просмотра. По ссылке доступна только последняя версия и её XML
 * (отдельным путём); всё остальное — отчёт, трассировка, дифф — уже лежит в ответе по ссылке,
 * поэтому версия собирается из `detail.latest_version` и загруженного XML.
 */
export function shareVersionSource(token: string, detail: ProjectDetail): VersionSource {
  const latest = detail.latest_version
  const xmlPath = (versionId: string) =>
    `/api/v1/shares/${encodeURIComponent(token)}/versions/${encodeURIComponent(versionId)}/xml`
  return {
    detail: (versionId) =>
      queryOptions<VersionDetail, Error, VersionDetail, QueryKey>({
        queryKey: [...shareKeys.shared(token), 'version', versionId],
        queryFn: async ({ signal }): Promise<VersionDetail> => {
          if (!latest || latest.id !== versionId) throw new Error('Версия недоступна по ссылке')
          const xml = unwrap(
            await api.GET('/api/v1/shares/{token}/versions/{version_id}/xml', {
              params: { path: { token, version_id: versionId } },
              parseAs: 'text',
              signal,
            }),
          ) as unknown as string
          return { ...latest, xml }
        },
        retry: false,
        staleTime: Number.POSITIVE_INFINITY,
      }),
    list: (projectId) =>
      queryOptions<Version[], Error, Version[], QueryKey>({
        queryKey: [...shareKeys.shared(token), 'versions', projectId],
        queryFn: async () => (latest ? [latest] : []),
        staleTime: Number.POSITIVE_INFINITY,
      }),
    xmlUrl: xmlPath,
    history: false,
  }
}

/**
 * Есть ли у вошедшего уже доступ к проекту: обычный запрос проекта отвечает 404, если нет.
 * Нужен, чтобы не предлагать «принять» владельцу и редактору. Для гостя не выполняется.
 * Ключ свой, а не `projectKeys.detail`: иначе уход со страницы отменил бы загрузку проекта,
 * которую уже начал loader следующего экрана (последний наблюдатель запроса отменяет его).
 */
export function useProjectAccess(projectId: string | undefined, enabled: boolean) {
  return useQuery({
    queryKey: ['share-access', projectId],
    queryFn: async ({ signal }) =>
      unwrap(
        await api.GET('/api/v1/projects/{project_id}', {
          params: { path: { project_id: projectId ?? '' } },
          signal,
        }),
      ).access,
    enabled: enabled && Boolean(projectId),
    retry: false,
    staleTime: 0,
    gcTime: 0,
  })
}

export function useAcceptInvite(token: string) {
  const client = useQueryClient()
  return useMutation({
    mutationFn: async () =>
      unwrap(await api.POST('/api/v1/shares/{token}/accept', { params: { path: { token } } })),
    // Проект теперь в списке «Общие».
    onSuccess: () => client.invalidateQueries({ queryKey: projectKeys.lists() }),
    onError: (error) =>
      toast.error('Не удалось сохранить доступ к проекту', { description: errorMessage(error) }),
  })
}
