import { QueryClient } from '@tanstack/react-query'

/**
 * Общие правила работы с серверными данными:
 * данные обновляются сами (фокус окна, SSE-инвалидация), кнопок «Обновить» в интерфейсе нет.
 */
export const queryClient = new QueryClient({
  defaultOptions: {
    queries: { staleTime: 15_000, refetchOnWindowFocus: true, retry: 2 },
  },
})
