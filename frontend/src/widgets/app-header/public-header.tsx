import { Link } from '@tanstack/react-router'
import type { ReactNode } from 'react'
import { useSession } from '@/entities/session'
import { AccountMenu } from '@/features/account-menu/account-menu'
import { ThemeSwitch } from '@/features/theme-switch/theme-switch'
import { cn } from '@/shared/lib/cn'
import { BrandMark, Button } from '@/shared/ui'

export interface PublicHeaderProps {
  /** Содержимое после знака: название проекта, маркер «Только просмотр». */
  children?: ReactNode
  /** Действия экрана перед темой и аккаунтом. */
  actions?: ReactNode
  /** Куда вернуть после входа (кнопка «Войти» для гостя). */
  loginRedirect?: string
  className?: string
}

/**
 * Узкая шапка публичных страниц (ссылки «поделиться»): знак, контекст, тема и аккаунт.
 * Без палитры команд и поиска — на публичной странице их нет. Гость видит «Войти»,
 * вошедший — меню аккаунта; на стенде без аккаунтов ни того ни другого.
 */
export function PublicHeader({ children, actions, loginRedirect, className }: PublicHeaderProps) {
  const session = useSession()
  const guest = session.data?.auth_enabled && !session.data.user
  return (
    <header
      className={cn(
        'relative z-20 flex h-14 shrink-0 items-center gap-3 border-b border-border bg-bg/85 px-4 backdrop-blur-md wide:px-5',
        className,
      )}
    >
      <Link
        to="/"
        aria-label="Архитектор"
        className="flex shrink-0 items-center gap-2.5 rounded-md outline-none focus-visible:ring-2 focus-visible:ring-focus-ring"
      >
        <BrandMark />
        <span className="type-subheading text-fg">Архитектор</span>
      </Link>
      <div className="flex min-w-0 flex-1 items-center gap-2">{children}</div>
      <div className="flex shrink-0 items-center gap-2">
        {actions}
        <ThemeSwitch compact />
        {guest && (
          <Button asChild size="sm">
            <Link to="/login" search={loginRedirect ? { redirect: loginRedirect } : {}}>
              Войти
            </Link>
          </Button>
        )}
        <AccountMenu afterLogout={() => window.location.reload()} />
      </div>
    </header>
  )
}
