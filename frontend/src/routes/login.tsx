import { createFileRoute } from '@tanstack/react-router'
import { type AuthMode, sanitizeRedirect, skipLoginIfSignedIn } from '@/entities/session'
import { LoginScreen } from '@/widgets/login-screen/login-screen'

interface LoginSearch {
  redirect?: string
  /** Режим формы: register — сразу «Регистрация»; для входа параметра нет. */
  mode?: 'register'
}

/**
 * Вход и регистрация. Публичный маршрут; кто уже вошёл (или аккаунтов нет) — уходит дальше.
 * Режим живёт в адресе (`/login?mode=register`): на регистрацию можно дать прямую ссылку,
 * а браузер сразу видит форму нужного типа.
 */
export const Route = createFileRoute('/login')({
  validateSearch: (search: Record<string, unknown>): LoginSearch => {
    const redirect = sanitizeRedirect(search.redirect)
    return {
      redirect: redirect === '/' ? undefined : redirect,
      mode: search.mode === 'register' ? 'register' : undefined,
    }
  },
  beforeLoad: ({ context, search }) => skipLoginIfSignedIn(context.queryClient, search.redirect),
  component: LoginRoute,
})

function LoginRoute() {
  const { redirect, mode } = Route.useSearch()
  const navigate = Route.useNavigate()
  const changeMode = (next: AuthMode) =>
    void navigate({
      search: (previous) => ({ ...previous, mode: next === 'register' ? 'register' : undefined }),
      replace: true,
    })
  return (
    <LoginScreen
      mode={mode ?? 'login'}
      onModeChange={changeMode}
      redirectTo={sanitizeRedirect(redirect)}
    />
  )
}
