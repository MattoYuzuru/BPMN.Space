import { createFileRoute, Outlet } from '@tanstack/react-router'
import { requireSession } from '@/entities/session'
import { OnboardingLayer } from '@/widgets/onboarding-checklist/onboarding-layer'

/**
 * Закрытый раздел: всё, что внутри, видит только вошедший пользователь (или любой — на стенде без
 * аккаунтов). Публичные маршруты — `/login`, `/styleguide`, `/dev/diagram` — лежат рядом, вне
 * этого раздела; ссылки «поделиться» тоже будут вне него.
 */
export const Route = createFileRoute('/_app')({
  beforeLoad: ({ context, location }) => requireSession(context.queryClient, location.href),
  component: AppLayout,
})

function AppLayout() {
  return (
    <>
      <Outlet />
      <OnboardingLayer />
    </>
  )
}
