import { queryOptions, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import type { Schemas } from '@/shared/api/client'
import { api, errorMessage, unwrap } from '@/shared/api/client'
import { toast } from '@/shared/ui'

export const toolCredentialKeys = {
  all: ['credentials'] as const,
  catalog: ['tool-catalog'] as const,
}

/** Каталог провайдеров: где взять ключ, бесплатный уровень, РФ, что закрывает модель. */
export const toolCatalogQueryOptions = queryOptions({
  queryKey: toolCredentialKeys.catalog,
  queryFn: async ({ signal }) => unwrap(await api.GET('/api/v1/me/tool-catalog', { signal })),
  staleTime: 10 * 60_000,
})

export function useToolCatalog() {
  return useQuery(toolCatalogQueryOptions)
}

export const toolCredentialsQueryOptions = queryOptions({
  queryKey: toolCredentialKeys.all,
  queryFn: async ({ signal }) => unwrap(await api.GET('/api/v1/me/credentials', { signal })),
  staleTime: 30_000,
})

export function useToolCredentials() {
  return useQuery(toolCredentialsQueryOptions)
}

/** Добавление ключа: сервер проверяет его у провайдера и сохраняет зашифрованным. */
export function useCreateToolCredential() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: async (body: Schemas['CredentialCreate']) =>
      unwrap(await api.POST('/api/v1/me/credentials', { body })),
    onSuccess: () => client.invalidateQueries({ queryKey: toolCredentialKeys.all }),
  })
}

/** Правка без замены ключа: название, приоритет, включённость, лимит, модель. */
export function useUpdateToolCredential() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: async ({ id, ...body }: Schemas['CredentialUpdate'] & { id: string }) =>
      unwrap(
        await api.PATCH('/api/v1/me/credentials/{credential_id}', {
          params: { path: { credential_id: id } },
          body,
        }),
      ),
    onSuccess: () => client.invalidateQueries({ queryKey: toolCredentialKeys.all }),
    onError: (error) =>
      toast.error('Не удалось сохранить ключ', { description: errorMessage(error) }),
  })
}

export function useDeleteToolCredential() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: async (id: string) =>
      unwrap(
        await api.DELETE('/api/v1/me/credentials/{credential_id}', {
          params: { path: { credential_id: id } },
        }),
      ),
    onSuccess: () => client.invalidateQueries({ queryKey: toolCredentialKeys.all }),
    onError: (error) =>
      toast.error('Не удалось удалить ключ', { description: errorMessage(error) }),
  })
}

/** Проверка ключа: успех снимает отметку ошибки, отказ показывает причину. */
export function useCheckToolCredential() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: async (id: string) =>
      unwrap(
        await api.POST('/api/v1/me/credentials/{credential_id}/check', {
          params: { path: { credential_id: id } },
        }),
      ),
    onSuccess: (result) => {
      if (result.ok) toast.success('Ключ работает')
      else toast.warning('Ключ не прошёл проверку', { description: result.detail })
      return client.invalidateQueries({ queryKey: toolCredentialKeys.all })
    },
    onError: (error) =>
      toast.error('Не удалось проверить ключ', { description: errorMessage(error) }),
  })
}
