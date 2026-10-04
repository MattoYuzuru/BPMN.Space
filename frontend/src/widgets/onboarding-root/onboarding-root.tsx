import { lazy, Suspense } from 'react'
import { useOnboarding } from '@/entities/onboarding'

// Приветствие и тур — отдельный чанк: стартовый бандл узнаёт только, включён ли онбординг.
const OnboardingGate = lazy(() => import('./onboarding-gate'))

/**
 * Обучение в закрытом разделе: приветствие после первого входа и тур. Без аккаунтов и при
 * выключенном онбординге (`enabled: false`) не делает ничего и ничего не грузит.
 */
export function OnboardingRoot() {
  const enabled = Boolean(useOnboarding().data?.enabled)
  if (!enabled) return null
  return (
    <Suspense fallback={null}>
      <OnboardingGate />
    </Suspense>
  )
}
