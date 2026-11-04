import {
  type QueryClient,
  queryOptions,
  useMutation,
  useQuery,
  useQueryClient,
} from '@tanstack/react-query'
import type { Schemas } from '@/shared/api/client'
import { api, errorMessage, unwrap } from '@/shared/api/client'
import { toast } from '@/shared/ui'
import { useModelChoiceStore } from './choice'
import type { LlmModel, ModelCapabilities } from './model'

export const llmCredentialKeys = {
  all: ['llm-credentials'] as const,
  models: (id: string) => ['llm-credentials', id, 'models'] as const,
}

/** Ключи в «Инструментах» — тот же набор: после мутации перечитываем и его. */
function invalidateToolCredentials(client: QueryClient) {
  void client.invalidateQueries({ queryKey: ['credentials'] })
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

/**
 * `background` — запрос для метки в шапке: без повторов при фокусе окна и при монтировании
 * после ошибки, чтобы неработающий ключ не дёргал провайдера на каждый показ страницы.
 */
export function useLlmModels(credentialId: string | undefined, { background = false } = {}) {
  return useQuery({
    ...llmModelsQueryOptions(credentialId ?? ''),
    enabled: Boolean(credentialId),
    ...(background ? { refetchOnWindowFocus: false, retryOnMount: false } : {}),
  })
}

/** Возможности модели из уже загруженного списка ключа (без запроса). */
export function cachedModelCapabilities(
  client: QueryClient,
  credentialId: string,
  model: string,
): ModelCapabilities | undefined {
  const models = client.getQueryData<LlmModel[]>(llmCredentialKeys.models(credentialId))
  return models?.find((item) => item.id === model)?.capabilities
}

/** Создание проверяет ключ у провайдера; ошибку показывает форма, а не тост. */
export function useCreateLlmCredential() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: async (body: Schemas['LlmCredentialCreate']) =>
      unwrap(await api.POST('/api/v1/me/llm-credentials', { body })),
    onSuccess: () => {
      invalidateToolCredentials(client)
      return client.invalidateQueries({ queryKey: llmCredentialKeys.all })
    },
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
    onSuccess: () => {
      invalidateToolCredentials(client)
      return client.invalidateQueries({ queryKey: llmCredentialKeys.all })
    },
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
      invalidateToolCredentials(client)
      return client.invalidateQueries({ queryKey: llmCredentialKeys.all })
    },
    onError: (error) => toast.error('Не удалось удалить', { description: errorMessage(error) }),
  })
}
