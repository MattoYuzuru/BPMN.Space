import { useQueryClient } from '@tanstack/react-query'
import { useEffect, useRef } from 'react'
import {
  CHECKLIST_TOTAL,
  type ChecklistItemKey,
  onboardingKeys,
  useChecklistView,
} from '@/entities/onboarding'
import { useCurrentUser } from '@/entities/session'
import { useTourStore } from '@/features/onboarding/tour/store'
import { subscribeOnboardingSignals } from '@/shared/lib/onboarding-signals'
import { dismissHintFor } from './active-hint'
import { announceProgress } from './progress-notices'
import { useRecentItems } from './recent'

/**
 * Единственное место, где сравниваются ответы `GET /me/onboarding`: что отметилось нового.
 * Первый ответ не объявляем (там то, что сделано раньше). Новый пункт вне тура — уведомление,
 * несколько сразу — одно сводное, последний — «Вы освоили Архитектор»; во время тура молчим
 * (у тура своя обратная связь). Подсказка про выполненный пункт закрывается сама. Заодно по
 * сигналу `run.finished` и после любой успешной мутации перечитывает состояние: сервер отмечает схему в конце прогона.
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

  // Любое успешное действие могло отметить пункт на сервере: перечитываем состояние. У мутаций нет
  // общего ключа, поэтому слушаем кэш мутаций (у выхода и отметок клиента — `skipOnboarding`).
  // Подписка здесь, а не в `app/`: это лениво подгружаемая часть и она живёт, пока есть аккаунт.
  useEffect(() => {
    if (!userId) return
    return client.getMutationCache().subscribe((event) => {
      if (event.type !== 'updated' || event.action.type !== 'success') return
      if (event.mutation.meta?.skipOnboarding) return
      void client.invalidateQueries({ queryKey: onboardingKeys.all })
    })
  }, [client, userId])

  const quiet = view.tourActive || tourRunning
  // Финал, наступивший во время тура, объявляем, когда тур закончится.
  const finalPending = useRef(false)
  useEffect(() => {
    if (!view.enabled) {
      previous.current = null
      finalPending.current = false
      return
    }
    const before = previous.current
    previous.current = { userId, keys: view.doneKeys, quiet }
    // Первая загрузка (или другой пользователь): запоминаем, ничего не объявляем.
    if (!before || before.userId !== userId) {
      finalPending.current = false
      return
    }
    const added = [...view.doneKeys].filter((key) => !before.keys.has(key))
    if (added.length > 0) {
      useRecentItems.getState().mark(added)
      dismissHintFor(added)
      // Тур мог закончиться в тот же момент, когда пришла отметка его последнего шага: тоже молчим.
      if (!quiet && !before.quiet) announceProgress(added, view.done)
      else if (view.done >= CHECKLIST_TOTAL) finalPending.current = true
    } else if (finalPending.current && !quiet) {
      finalPending.current = false
      announceProgress([...view.doneKeys].slice(-1), view.done)
    }
  }, [view.enabled, view.doneKeys, view.done, userId, quiet])

  return null
}
