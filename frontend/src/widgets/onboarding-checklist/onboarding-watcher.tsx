import { useQueryClient } from '@tanstack/react-query'
import { useEffect, useRef } from 'react'
import { type ChecklistItemKey, onboardingKeys, useChecklistView } from '@/entities/onboarding'
import { useCurrentUser } from '@/entities/session'
import { useTourStore } from '@/features/onboarding/tour/store'
import { subscribeOnboardingSignals } from '@/shared/lib/onboarding-signals'
import { announceProgress } from './progress-notices'
import { useRecentItems } from './recent'
import { dismissHintFor } from './visit'

/**
 * Единственное место, где сравниваются ответы `GET /me/onboarding`: что отметилось нового.
 * Первый ответ не объявляем (там то, что сделано раньше). Новый пункт вне тура — уведомление,
 * несколько сразу — одно сводное, последний — «Вы освоили Архитектор»; во время тура молчим
 * (у тура своя обратная связь). Подсказка про выполненный пункт закрывается сама. Заодно по
 * сигналу `run.finished` перечитывает состояние: сервер отмечает схему в конце прогона.
 */
export function OnboardingWatcher() {
  const client = useQueryClient()
  const userId = useCurrentUser()?.id
  const view = useChecklistView()
  const tourRunning = useTourStore((state) => state.status === 'active')
  const previous = useRef<{
    userId: string | undefined
    keys: ReadonlySet<ChecklistItemKey>
    quiet: boolean
  } | null>(null)

  // Прогон завершился: сервер уже мог отметить схему. Подписка живёт всё время работы в аккаунте.
  useEffect(
    () =>
      subscribeOnboardingSignals((signal) => {
        if (signal.type === 'run.finished') {
          void client.invalidateQueries({ queryKey: onboardingKeys.all })
        }
      }),
    [client],
  )

  const quiet = view.tourActive || tourRunning
  useEffect(() => {
    if (!view.enabled) {
      previous.current = null
      return
    }
    const before = previous.current
    previous.current = { userId, keys: view.doneKeys, quiet }
    // Первая загрузка (или другой пользователь): запоминаем, ничего не объявляем.
    if (!before || before.userId !== userId) return
    const added = [...view.doneKeys].filter((key) => !before.keys.has(key))
    if (added.length === 0) return
    useRecentItems.getState().mark(added)
    dismissHintFor(added)
    // Тур мог закончиться в тот же момент, когда пришла отметка его последнего шага: тоже молчим.
    if (!quiet && !before.quiet) announceProgress(added, view.done)
  }, [view.enabled, view.doneKeys, view.done, userId, quiet])

  return null
}
