import { useNavigate } from '@tanstack/react-router'
import type { ReactNode } from 'react'
import { CHECKLIST_TOTAL, useChecklistView, useOnboardingUi } from '@/entities/onboarding'
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
  ProgressRing,
  Tooltip,
  toast,
} from '@/shared/ui'

/**
 * Меню аккаунта в шапке. Без аккаунтов (стенд без входа) и для гостя его нет. Пункт «Начало
 * работы» есть только там, где смонтирована панель чек-листа (закрытый раздел): на публичных
 * страницах `withChecklist={false}`.
 */
export function AccountMenu({
  afterLogout,
  withChecklist = true,
}: {
  afterLogout?: () => void
  withChecklist?: boolean
}) {
  const session = useSession()
  const user = session.data?.auth_enabled ? session.data.user : null
  if (!user) return null
  return (
    <AccountMenuFor
      user={user}
      afterLogout={afterLogout}
      checklist={withChecklist ? <ChecklistMenuItem /> : undefined}
    />
  )
}

/** Пункт «Начало работы» с кольцом прогресса; пока онбординга нет (выключен, не загружен), его нет. */
function ChecklistMenuItem() {
  const view = useChecklistView()
  const openChecklist = useOnboardingUi((state) => state.openChecklist)
  if (!view.enabled) return null
  return <ChecklistMenuItemView done={view.done} onSelect={openChecklist} />
}

/** Сам пункт: подпись, кольцо прогресса и счётчик «5/12»; выполнены все 12 — зелёное кольцо с галочкой. */
export function ChecklistMenuItemView({
  done,
  total = CHECKLIST_TOTAL,
  onSelect,
}: {
  done: number
  total?: number
  onSelect: () => void
}) {
  return (
    <DropdownMenuItem icon="list-check" onSelect={onSelect}>
      <span className="flex w-full items-center gap-2">
        <span className="flex-1">Начало работы</span>
        <span className="type-caption text-fg-subtle" data-numeric>
          {done}/{total}
        </span>
        <ProgressRing value={done} max={total} size={18} />
      </span>
    </DropdownMenuItem>
  )
}

/**
 * Меню конкретного пользователя: почта, пункт чек-листа (если передан) и выход; для витрины
 * стайлгайда принимает пользователя и пункт напрямую.
 */
export function AccountMenuFor({
  user,
  onLogout,
  afterLogout,
  checklist,
}: {
  user: SessionUser
  onLogout?: () => void
  /** Что делать после выхода вместо перехода на экран входа (публичные страницы остаются на месте). */
  afterLogout?: () => void
  /** Пункт «Начало работы» между почтой и «Выйти». */
  checklist?: ReactNode
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
        {checklist}
        <DropdownMenuItem icon="logout" onSelect={signOut}>
          Выйти
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  )
}
