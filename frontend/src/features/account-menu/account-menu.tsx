import { useNavigate } from '@tanstack/react-router'
import { emailInitialsName, type SessionUser, useLogout, useSession } from '@/entities/session'
import {
  Avatar,
  Button,
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
  Tooltip,
  toast,
} from '@/shared/ui'

/** Меню аккаунта в шапке. Без аккаунтов (стенд без входа) и для гостя его нет. */
export function AccountMenu({ afterLogout }: { afterLogout?: () => void }) {
  const session = useSession()
  const user = session.data?.auth_enabled ? session.data.user : null
  if (!user) return null
  return <AccountMenuFor user={user} afterLogout={afterLogout} />
}

/** Меню конкретного пользователя: почта и выход; для витрины стайлгайда принимает пользователя напрямую. */
export function AccountMenuFor({
  user,
  onLogout,
  afterLogout,
}: {
  user: SessionUser
  onLogout?: () => void
  /** Что делать после выхода вместо перехода на экран входа (публичные страницы остаются на месте). */
  afterLogout?: () => void
}) {
  const logout = useLogout()
  const navigate = useNavigate()

  const signOut = () => {
    if (onLogout) return onLogout()
    logout.mutate(undefined, {
      onSuccess: () =>
        afterLogout ? afterLogout() : void navigate({ to: '/login', replace: true }),
      onError: () => toast.error('Не удалось выйти', { description: 'Повторите попытку.' }),
    })
  }

  return (
    <DropdownMenu>
      <Tooltip content="Аккаунт" side="bottom">
        <DropdownMenuTrigger asChild>
          <Button
            variant="ghost"
            size="sm"
            aria-label="Аккаунт"
            className="size-7 rounded-full px-0"
          >
            <Avatar name={emailInitialsName(user.email)} size="md" />
          </Button>
        </DropdownMenuTrigger>
      </Tooltip>
      <DropdownMenuContent align="end" className="min-w-56">
        <DropdownMenuLabel className="truncate">{user.email}</DropdownMenuLabel>
        <DropdownMenuSeparator />
        <DropdownMenuItem icon="logout" onSelect={signOut}>
          Выйти
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  )
}
