import { MutationCache, QueryCache, QueryClient } from '@tanstack/react-query'
import { onboardingKeys } from '@/entities/onboarding'
import { ApiError } from '@/shared/api/client'
import { toast } from '@/shared/ui'

/** Коды, при которых повтор запроса бессмыслен: нет входа, нет прав, слишком частые запросы. */
const NO_RETRY = new Set([401, 403, 429])

/** Повторять сбойный запрос не больше двух раз и только при временных сбоях. */
export function shouldRetry(failureCount: number, error: unknown): boolean {
  if (error instanceof ApiError && NO_RETRY.has(error.status)) return false
  return failureCount < 2
}

let unauthorizedHandler: (() => void) | undefined

/** Роутер подписывается на «сессия закончилась» после создания: кэш создаётся раньше него. */
export function setUnauthorizedHandler(handler: (() => void) | undefined) {
  unauthorizedHandler = handler
}

/**
 * Общая реакция на ошибки: 401 — сессия закончилась, ведём на вход; 429 в запросах чтения —
 * спокойное сообщение (у действий своё уведомление об ошибке, второе не нужно).
 */
function onQueryError(error: unknown) {
  if (!(error instanceof ApiError)) return
  if (error.status === 401) unauthorizedHandler?.()
  if (error.status === 429) {
    toast.warning('Слишком много запросов', {
      description: 'Подождите немного и повторите.',
      id: 'rate-limit',
    })
  }
}

function onMutationError(error: unknown) {
  if (error instanceof ApiError && error.status === 401) unauthorizedHandler?.()
}

/**
 * Общие правила работы с серверными данными:
 * данные обновляются сами (фокус окна, SSE-инвалидация), кнопок «Обновить» в интерфейсе нет.
 */
export const queryClient = new QueryClient({
  queryCache: new QueryCache({ onError: onQueryError }),
  mutationCache: new MutationCache({
    onError: onMutationError,
    // Любое успешное действие (создали проект, ответили, загрузили файл) могло отметить пункт
    // «Начала работы» на сервере: состояние онбординга перечитывается. Запрос дешёвый, а у
    // мутаций нет общего ключа, по которому можно было бы отфильтровать нужные.
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: onboardingKeys.all }),
  }),
  defaultOptions: {
    queries: { staleTime: 15_000, refetchOnWindowFocus: true, retry: shouldRetry },
  },
})
