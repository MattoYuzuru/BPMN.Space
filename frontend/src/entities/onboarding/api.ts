import { queryOptions, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useCurrentUser } from '@/entities/session'
import { api, errorMessage, type Schemas, unwrap } from '@/shared/api/client'
import { toast } from '@/shared/ui'
import type { ChecklistItemKey } from './items'
import { isItemDone, type OnboardingState, type OnboardingTarget, withCompletedItem } from './model'

export type TourUpdate = Schemas['TourUpdate']

/** Ключи запросов. Корень включает пользователя: состояние онбординга у каждого своё. */
export const onboardingKeys = {
  all: ['onboarding'] as const,
  user: (userId: string | undefined) => [...onboardingKeys.all, userId ?? 'guest'] as const,
}

export function onboardingQueryOptions(userId: string | undefined) {
  return queryOptions({
    queryKey: onboardingKeys.user(userId),
    queryFn: async ({ signal }): Promise<OnboardingState> =>
      unwrap(await api.GET('/api/v1/me/onboarding', { signal })),
    // Состояние меняют сами мутации (они кладут ответ в кэш); свежесть нужна для отметок сервера.
    staleTime: 30_000,
  })
}

/**
 * Состояние тура и чек-листа текущего пользователя. Гостю и стенду без аккаунтов запрос не
 * уходит; при выключенном онбординге сервер отвечает `enabled: false`.
 */
export function useOnboarding() {
  const userId = useCurrentUser()?.id
  return useQuery({ ...onboardingQueryOptions(userId), enabled: Boolean(userId) })
}

/** Ключ состояния текущего пользователя для ручной работы с кэшем. */
export function useOnboardingKey() {
  return onboardingKeys.user(useCurrentUser()?.id)
}

/** Смена шага или статуса тура. Ответ сервера становится состоянием; при отказе (409) — перечитывание. */
export function useUpdateTour() {
  const client = useQueryClient()
  const key = useOnboardingKey()
  return useMutation({
    // Ответ сервера сам становится состоянием: общее перечитывание не нужно.
    meta: { skipOnboarding: true },
    mutationFn: async (body: TourUpdate) =>
      unwrap(await api.PATCH('/api/v1/me/onboarding/tour', { body })),
    onSuccess: (state) => client.setQueryData<OnboardingState>(key, state),
    onError: () => client.invalidateQueries({ queryKey: key }),
  })
}

/** «Пройти обучение заново». */
export function useRestartTour() {
  const client = useQueryClient()
  const key = useOnboardingKey()
  return useMutation({
    // Ответ сервера сам становится состоянием: общее перечитывание не нужно.
    meta: { skipOnboarding: true },
    mutationFn: async () => unwrap(await api.POST('/api/v1/me/onboarding/tour/restart')),
    onSuccess: (state) => client.setQueryData<OnboardingState>(key, state),
    onError: (error) =>
      toast.error('Не удалось запустить обучение', { description: errorMessage(error) }),
  })
}

/** Скрыть или вернуть плашку «Начало работы»; плашка меняется сразу, при ошибке возвращается. */
export function useSetChecklistHidden() {
  const client = useQueryClient()
  const key = useOnboardingKey()
  return useMutation({
    // Ответ сервера сам становится состоянием: общее перечитывание не нужно.
    meta: { skipOnboarding: true },
    mutationFn: async (hidden: boolean) =>
      unwrap(await api.PATCH('/api/v1/me/onboarding/checklist', { body: { hidden } })),
    onMutate: async (hidden) => {
      await client.cancelQueries({ queryKey: key })
      const previous = client.getQueryData<OnboardingState>(key)
      client.setQueryData<OnboardingState>(key, (state) =>
        state?.checklist ? { ...state, checklist: { ...state.checklist, hidden } } : state,
      )
      return { previous }
    },
    onError: (error, _hidden, context) => {
      if (context?.previous) client.setQueryData(key, context.previous)
      toast.error('Не удалось сохранить настройку', { description: errorMessage(error) })
    },
    onSuccess: (state) => client.setQueryData<OnboardingState>(key, state),
  })
}

/** Отметки в пути: не шлём одно и то же действие дважды, пока первая отправка не завершилась. */
const reporting = new Set<string>()

/**
 * Сообщить о действии, которого не видит сервер (`simulation_run`, `diagram_exported`).
 * Если пункт уже отмечен в кэше (или онбординга нет), запрос не уходит. Ошибка не показывается:
 * это фоновая отметка, пользователь о ней не просил.
 */
export function useReportOnboardingEvent() {
  const client = useQueryClient()
  const userId = useCurrentUser()?.id
  const key = useOnboardingKey()
  return useMutation({
    // Сама отметка кладёт состояние в кэш и перечитывает его ниже: общий перехват не нужен.
    meta: { skipOnboarding: true },
    mutationFn: async (item: ChecklistItemKey): Promise<'sent' | 'skipped'> => {
      if (!userId) return 'skipped'
      // Состояние могло ещё не загрузиться (событие раньше первого запроса): дожидаемся его,
      // иначе отметка молча потерялась бы. Не загрузилось — не знаем, нужна ли она, не шлём.
      const state = await client
        .ensureQueryData(onboardingQueryOptions(userId))
        .catch(() => undefined)
      const flight = `${key.join('/')}:${item}`
      if (!state?.enabled || isItemDone(state, item) || reporting.has(flight)) return 'skipped'
      reporting.add(flight)
      try {
        unwrap(await api.POST('/api/v1/me/onboarding/events', { body: { item } }))
        return 'sent'
      } finally {
        reporting.delete(flight)
      }
    },
    onSuccess: (result, item) => {
      if (result !== 'sent') return
      client.setQueryData<OnboardingState>(
        key,
        (state) => state && withCompletedItem(state, item, 'client', new Date().toISOString()),
      )
      return client.invalidateQueries({ queryKey: key })
    },
  })
}

/** Куда вести по невыполненному пункту чек-листа. */
export async function fetchItemTarget(
  item: ChecklistItemKey,
  signal?: AbortSignal,
): Promise<OnboardingTarget> {
  return unwrap(
    await api.GET('/api/v1/me/onboarding/items/{item}/target', {
      params: { path: { item } },
      signal,
    }),
  )
}
