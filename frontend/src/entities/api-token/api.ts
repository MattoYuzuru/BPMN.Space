import { queryOptions, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import type { Schemas } from '@/shared/api/client'
import { api, errorMessage, unwrap } from '@/shared/api/client'
import { toast } from '@/shared/ui'

export const apiTokenKeys = {
  all: ['api-tokens'] as const,
  projects: ['api-tokens', 'projects'] as const,
}

export const apiTokensQueryOptions = queryOptions({
  queryKey: apiTokenKeys.all,
  queryFn: async ({ signal }) => unwrap(await api.GET('/api/v1/me/api-tokens', { signal })).items,
  staleTime: 30_000,
})

export function useApiTokens() {
  return useQuery(apiTokensQueryOptions)
}

/** Сколько проектов показываем в выборе: столько же сервер принимает в одном токене. */
const PROJECT_CHOICES_LIMIT = 100

export interface TokenProjectChoice {
  id: string
  title: string
}

/**
 * Проекты, которыми можно ограничить токен: свои и принятые по ссылке (без демо-примеров).
 * Список нужен и для подписей в строках токенов, поэтому кэшируется отдельно от главной.
 */
export function useTokenProjectChoices() {
  return useQuery({
    queryKey: apiTokenKeys.projects,
    queryFn: async ({ signal }) => {
      const pages = await Promise.all(
        (['own', 'shared'] as const).map(async (scope) =>
          unwrap(
            await api.GET('/api/v1/projects', {
              params: { query: { scope, limit: PROJECT_CHOICES_LIMIT } },
              signal,
            }),
          ),
        ),
      )
      const seen = new Set<string>()
      const choices: TokenProjectChoice[] = []
      for (const project of pages.flatMap((page) => page.items)) {
        if (seen.has(project.id)) continue
        seen.add(project.id)
        choices.push({ id: project.id, title: project.title })
      }
      return choices
    },
    staleTime: 30_000,
  })
}

/** Создание: ошибку показывает форма, секрет — один раз в том же окне. */
export function useCreateApiToken() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: async (body: Schemas['ApiTokenCreate']) =>
      unwrap(await api.POST('/api/v1/me/api-tokens', { body })),
    onSuccess: () => client.invalidateQueries({ queryKey: apiTokenKeys.all, exact: true }),
  })
}

export function useRevokeApiToken() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: async (id: string) =>
      unwrap(
        await api.DELETE('/api/v1/me/api-tokens/{token_id}', {
          params: { path: { token_id: id } },
        }),
      ),
    onSuccess: () => client.invalidateQueries({ queryKey: apiTokenKeys.all, exact: true }),
    onError: (error) =>
      toast.error('Не удалось отозвать токен', { description: errorMessage(error) }),
  })
}
