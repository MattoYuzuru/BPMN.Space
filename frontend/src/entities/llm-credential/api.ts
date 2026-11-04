import { queryOptions, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import type { Schemas } from '@/shared/api/client'
import { api, errorMessage, unwrap } from '@/shared/api/client'
import { toast } from '@/shared/ui'
import { useModelChoiceStore } from './choice'

export const llmCredentialKeys = {
  all: ['llm-credentials'] as const,
  models: (id: string) => ['llm-credentials', id, 'models'] as const,
}

export const llmCredentialsQueryOptions = queryOptions({
  queryKey: llmCredentialKeys.all,
  queryFn: async ({ signal }) => unwrap(await api.GET('/api/v1/me/llm-credentials', { signal })),
  staleTime: 30_000,
})

export function useLlmCredentials(enabled = true) {
  return useQuery({ ...llmCredentialsQueryOptions, enabled })
}

/** Модели ключа: провайдер спрашивается раз в несколько минут (кэш и на сервере). */
export function llmModelsQueryOptions(credentialId: string) {
  return queryOptions({
    queryKey: llmCredentialKeys.models(credentialId),
    queryFn: async ({ signal }) =>
      unwrap(
        await api.GET('/api/v1/me/llm-credentials/{credential_id}/models', {
          params: { path: { credential_id: credentialId } },
          signal,
        }),
      ).items,
    staleTime: 5 * 60_000,
    retry: false,
  })
}

export function useLlmModels(credentialId: string | undefined) {
  return useQuery({
    ...llmModelsQueryOptions(credentialId ?? ''),
    enabled: Boolean(credentialId),
  })
}

/** Создание проверяет ключ у провайдера; ошибку показывает форма, а не тост. */
export function useCreateLlmCredential() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: async (body: Schemas['LlmCredentialCreate']) =>
      unwrap(await api.POST('/api/v1/me/llm-credentials', { body })),
    onSuccess: () => client.invalidateQueries({ queryKey: llmCredentialKeys.all }),
  })
}

export function useUpdateLlmCredential() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: async ({ id, ...body }: Schemas['LlmCredentialUpdate'] & { id: string }) =>
      unwrap(
        await api.PATCH('/api/v1/me/llm-credentials/{credential_id}', {
          params: { path: { credential_id: id } },
          body,
        }),
      ),
    onSuccess: () => client.invalidateQueries({ queryKey: llmCredentialKeys.all }),
    onError: (error) => toast.error('Не удалось сохранить', { description: errorMessage(error) }),
  })
}

export function useDeleteLlmCredential() {
  const client = useQueryClient()
  const forget = useModelChoiceStore((state) => state.forget)
  return useMutation({
    mutationFn: async (id: string) =>
      unwrap(
        await api.DELETE('/api/v1/me/llm-credentials/{credential_id}', {
          params: { path: { credential_id: id } },
        }),
      ),
    onSuccess: (_data, id) => {
      forget(id)
      return client.invalidateQueries({ queryKey: llmCredentialKeys.all })
    },
    onError: (error) => toast.error('Не удалось удалить', { description: errorMessage(error) }),
  })
}
