import { createFileRoute } from '@tanstack/react-router'
import { sanitizeRedirect, skipLoginIfSignedIn } from '@/entities/session'
import { LoginScreen } from '@/widgets/login-screen/login-screen'

interface LoginSearch {
  redirect?: string
}

/** Вход и регистрация. Публичный маршрут; кто уже вошёл (или аккаунтов нет) — уходит дальше. */
export const Route = createFileRoute('/login')({
  validateSearch: (search: Record<string, unknown>): LoginSearch => {
    const redirect = sanitizeRedirect(search.redirect)
    return { redirect: redirect === '/' ? undefined : redirect }
  },
  beforeLoad: ({ context, search }) => skipLoginIfSignedIn(context.queryClient, search.redirect),
  component: LoginRoute,
})

function LoginRoute() {
  const { redirect } = Route.useSearch()
  return <LoginScreen redirectTo={sanitizeRedirect(redirect)} />
}
