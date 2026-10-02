import { queryOptions } from '@tanstack/react-query'
import { api, type Schemas, unwrap } from '@/shared/api/client'

export type Example = Schemas['Example']

/** Демо-примеры не меняются за сессию — грузим один раз, когда пользователь открыл создание. */
export const examplesQueryOptions = queryOptions({
  queryKey: ['examples'] as const,
  queryFn: async ({ signal }) => unwrap(await api.GET('/api/v1/examples', { signal })),
  staleTime: Number.POSITIVE_INFINITY,
})
