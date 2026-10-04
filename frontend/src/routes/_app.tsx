import { createFileRoute, Outlet } from '@tanstack/react-router'
import { requireSession } from '@/entities/session'
import { OnboardingRoot } from '@/widgets/onboarding-root/onboarding-root'

/**
 * Закрытый раздел: всё, что внутри, видит только вошедший пользователь (или любой — на стенде без
 * аккаунтов). Публичные маршруты — `/login`, `/styleguide`, `/dev/diagram` — лежат рядом, вне
 * этого раздела; ссылки «поделиться» тоже будут вне него.
 */
export const Route = createFileRoute('/_app')({
  beforeLoad: ({ context, location }) => requireSession(context.queryClient, location.href),
  component: AppLayout,
})

/** Экран раздела и обучение поверх него (приветствие, тур). */
function AppLayout() {
  return (
    <>
      <Outlet />
      <OnboardingRoot />
    </>
  )
}
