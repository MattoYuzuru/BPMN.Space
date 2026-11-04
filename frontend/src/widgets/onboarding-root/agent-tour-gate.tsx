import { useEffect } from 'react'
import { useApiTokens } from '@/entities/api-token'
import { useOnboardingUi } from '@/entities/onboarding'
import {
  AGENT_CHAPTERS,
  AGENT_COPY,
  type AgentTourContext,
  agentTourPersistence,
  agentTourSteps,
  startAgentTour,
} from '@/features/onboarding/agent-tour'
import { TourHost } from '@/features/onboarding/tour'
import { toast } from '@/shared/ui'

/**
 * Клиентский тур для агентов: тот же движок и хост, что у основного сценария, но свои шаги,
 * свой контекст и хранение в localStorage. Монтируется только по явной просьбе из раздела
 * «Доступ для агентов» (никогда при входе), поэтому в стартовый бандл не попадает.
 */
export default function AgentTourGate() {
  const request = useOnboardingUi((state) => state.agentTourRequest)
  const tokens = useApiTokens()
  const context: AgentTourContext = { tokenCount: tokens.data?.length ?? 0 }

  // Растёт на каждую просьбу (в том числе повторную после закрытия): тур начинается заново
  // или продолжается с сохранённого шага.
  useEffect(() => {
    if (request > 0) startAgentTour()
  }, [request])

  return (
    <TourHost
      steps={agentTourSteps}
      context={context}
      persistence={agentTourPersistence}
      chapters={AGENT_CHAPTERS}
      restore={false}
      onEnd={(reason) => {
        if (reason === 'completed') toast.success(AGENT_COPY.finishToast)
      }}
    />
  )
}
