import { lazy, Suspense } from 'react'
import { useOnboarding, useOnboardingUi } from '@/entities/onboarding'

// Приветствие и тур — отдельный чанк: стартовый бандл узнаёт только, включён ли онбординг.
const OnboardingGate = lazy(() => import('./onboarding-gate'))
// Агентский тур — свой чанк: грузится только по просьбе из «Доступа для агентов».
const AgentTourGate = lazy(() => import('./agent-tour-gate'))

/**
 * Обучение в закрытом разделе: приветствие после первого входа, тур из 11 шагов и отдельный
 * клиентский тур для агентов. Без аккаунтов и при выключенном онбординге серверный сценарий
 * не делает ничего; агентский тур запускается только явной кнопкой и от сервера не зависит.
 */
export function OnboardingRoot() {
  const enabled = Boolean(useOnboarding().data?.enabled)
  return (
    <>
      <AgentTourMount />
      {enabled && (
        <Suspense fallback={null}>
          <OnboardingGate />
        </Suspense>
      )}
    </>
  )
}

/** Загрузка агентского тур-хоста только после просьбы: без клика чанк не загружается. */
function AgentTourMount() {
  const requested = useOnboardingUi((state) => state.agentTourRequest > 0)
  if (!requested) return null
  return (
    <Suspense fallback={null}>
      <AgentTourGate />
    </Suspense>
  )
}
