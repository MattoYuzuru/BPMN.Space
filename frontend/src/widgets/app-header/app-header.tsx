import { Link } from '@tanstack/react-router'
import type { ReactNode } from 'react'
import { openCommandPalette } from '@/features/command-palette/model'
import { ThemeSwitch } from '@/features/theme-switch/theme-switch'
import { cn } from '@/shared/lib/cn'
import { BrandMark, Button, Kbd, Tooltip } from '@/shared/ui'

export interface AppHeaderProps {
  /** Содержимое после знака: хлебные крошки, название проекта. */
  children?: ReactNode
  /** Действия экрана перед общими (палитра, тема). */
  actions?: ReactNode
  /** Нижняя кромка: линия тока во время прогона. */
  edge?: ReactNode
  /** Только знак без названия — когда шапке нужно место (рабочее место проекта). */
  compactBrand?: boolean
  className?: string
}

/** Шапка приложения: знак, контекст экрана, палитра команд и тема. Высота 56 px. */
export function AppHeader({
  children,
  actions,
  edge,
  compactBrand = false,
  className,
}: AppHeaderProps) {
  return (
    <header
      className={cn(
        'relative z-20 flex h-14 shrink-0 items-center gap-3 border-b border-border bg-bg/85 px-4 backdrop-blur-md wide:px-5',
        className,
      )}
    >
      <Tooltip content="Все проекты" side="bottom">
        <Link
          to="/"
          aria-label="Архитектор — все проекты"
          className="flex shrink-0 items-center gap-2.5 rounded-md outline-none focus-visible:ring-2 focus-visible:ring-focus-ring"
        >
          <BrandMark />
          <span className={cn('type-subheading text-fg', compactBrand && 'sr-only')}>
            Архитектор
          </span>
        </Link>
      </Tooltip>
      <div className="flex min-w-0 flex-1 items-center gap-2">{children}</div>
      <div className="flex shrink-0 items-center gap-2">
        {actions}
        <Button
          variant="ghost"
          size="sm"
          leadingIcon="search"
          onClick={openCommandPalette}
          aria-label="Палитра команд"
          className="gap-2 text-fg-subtle"
        >
          <span className={compactBrand ? 'hidden ultra:inline' : 'hidden wide:inline'}>
            Команды
          </span>
          <Kbd keys={['mod', 'k']} />
        </Button>
        <ThemeSwitch compact />
      </div>
      {edge}
    </header>
  )
}
