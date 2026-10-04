import type { QueryClient } from '@tanstack/react-query'
import {
  type OnboardingState,
  onboardingKeys,
  onboardingQueryOptions,
  type TourStepKey,
  type TourUpdate,
} from '@/entities/onboarding'
import { useTourSession } from './session'
import type { TourPersistence } from './types'

export interface TourPersistenceDeps {
  client: QueryClient
  userId: string | undefined
  /** `PATCH /me/onboarding/tour`: ответ сервера уже кладётся в кэш состояния. */
  update: (body: TourUpdate) => Promise<unknown>
}

/**
 * Хранилище тура поверх `entities/onboarding`. Состояние берётся из того же кэша, что у приветствия
 * и чек-листа: повторная запись того, что сервер уже знает (шаг, к которому пришли из приветствия),
 * не уходит. Учебный проект сообщается вместе с первым шагом после его создания.
 */
export function createTourPersistence({
  client,
  userId,
  update,
}: TourPersistenceDeps): TourPersistence {
  const cached = () => client.getQueryData<OnboardingState>(onboardingKeys.user(userId))?.tour

  return {
    load: async () => {
      const state = await client.fetchQuery({ ...onboardingQueryOptions(userId), staleTime: 0 })
      return { status: state.tour?.status ?? 'pending', step: state.tour?.step ?? null }
    },
    saveStep: (step) => {
      const tour = cached()
      const projectId = useTourSession.getState().projectId
      const body: TourUpdate = { step: step as TourStepKey }
      const newProject = projectId !== null && tour?.project_id !== projectId
      if (newProject) body.project_id = projectId
      if (!newProject && tour?.status === 'active' && tour.step === step) return undefined
      return update(body)
    },
    setStatus: (status) => {
      if (status === 'active' && cached()?.status === 'active') return undefined
      return update({ status })
    },
  }
}
