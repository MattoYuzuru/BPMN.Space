import { useQueryErrorResetBoundary } from '@tanstack/react-query'
import { type ErrorComponentProps, Link, useRouter } from '@tanstack/react-router'
import { useEffect } from 'react'
import { ApiError, errorMessage } from '@/shared/api/client'
import { BrandMark, Button, EmptyState, GridBackdrop } from '@/shared/ui'
import { AppHeader } from '@/widgets/app-header/app-header'
import { PublicHeader } from '@/widgets/app-header/public-header'

/** 404: адрес не найден. Спокойный экран на сетке, путь назад — к проектам. */
export function NotFoundScreen() {
  return (
    <div className="flex min-h-dvh flex-col bg-bg">
      <AppHeader />
      <main className="relative isolate grid flex-1 place-items-center px-6">
        <GridBackdrop pattern="grid" glow />
        <div className="flex max-w-md flex-col items-center gap-5 text-center">
          <BrandMark size="lg" />
          <span className="type-code text-fg-subtle">404</span>
          <h1 className="type-title text-fg">Такой страницы нет</h1>
          <p className="type-body text-fg-muted">
            Возможно, проект удалён или ссылка скопирована не полностью.
          </p>
          <Button asChild variant="primary" leadingIcon="layout-grid">
            <Link to="/">Перейти к проектам</Link>
          </Button>
        </div>
      </main>
    </div>
  )
}

/**
 * Ошибка маршрута (errorComponent): что случилось и что сделать. «Повторить» сбрасывает
 * ошибки запросов и перезапускает loader'ы.
 */
export function RouteErrorScreen({ error, reset }: ErrorComponentProps) {
  const router = useRouter()
  const queryReset = useQueryErrorResetBoundary()
  useEffect(() => queryReset.reset(), [queryReset])

  const notFound = error instanceof ApiError && error.status === 404
  const offline = error instanceof TypeError
  const title = notFound
    ? 'Проект не найден'
    : offline
      ? 'Нет связи с сервером'
      : 'Не удалось открыть страницу'
  const description = notFound
    ? 'Его могли удалить. Остальные проекты — в общем списке.'
    : offline
      ? 'Проверьте подключение и повторите.'
      : error instanceof ApiError
        ? error.message
        : 'Повторите попытку. Если ошибка не уходит, обновите страницу.'

  return (
    <div className="flex min-h-dvh flex-col bg-bg">
      <AppHeader />
      <main className="relative flex flex-1">
        <EmptyState
          className="flex-1"
          icon={notFound ? 'search-off' : 'alert-circle'}
          title={title}
          description={description}
          action={
            <>
              {!notFound && (
                <Button
                  variant="primary"
                  onClick={() => {
                    reset()
                    void router.invalidate()
                  }}
                >
                  Повторить
                </Button>
              )}
              <Button asChild variant={notFound ? 'primary' : 'secondary'}>
                <Link to="/">К проектам</Link>
              </Button>
            </>
          }
        />
      </main>
    </div>
  )
}

const SHARE_STATES = {
  invalid: {
    icon: 'link',
    title: 'Ссылка недействительна',
    description: 'Её отозвали, или адрес скопирован не полностью.',
  },
  expired: {
    icon: 'clock',
    title: 'Срок действия ссылки истёк',
    description: 'Попросите владельца проекта создать новую.',
  },
  failed: {
    icon: 'alert-circle',
    title: 'Не удалось открыть ссылку',
    description: '',
  },
} as const

/**
 * Публичная ссылка не открылась: недействительна (отозвана или неверный адрес), срок истёк или
 * сбой связи. Каркас как у экрана ошибки маршрута; «Повторить» только там, где повтор поможет.
 */
export function ShareStateScreen(props: ShareStateProps) {
  return (
    <div className="flex min-h-dvh flex-col bg-bg">
      <PublicHeader />
      <main className="relative flex flex-1">
        <ShareStateBody className="flex-1" {...props} />
      </main>
    </div>
  )
}

interface ShareStateProps {
  kind: keyof typeof SHARE_STATES
  error?: unknown
  onRetry?: () => void
}

/** Содержимое экрана недоступной ссылки без шапки — его же показывает витрина стайлгайда. */
export function ShareStateBody({
  kind,
  error,
  onRetry,
  className,
}: ShareStateProps & { className?: string }) {
  const state = SHARE_STATES[kind]
  return (
    <EmptyState
      className={className}
      icon={state.icon}
      title={state.title}
      description={kind === 'failed' ? errorMessage(error) : state.description}
      action={
        <>
          {kind === 'failed' && onRetry && (
            <Button variant="primary" onClick={onRetry}>
              Повторить
            </Button>
          )}
          <Button asChild variant={kind === 'failed' ? 'secondary' : 'primary'}>
            <Link to="/">К проектам</Link>
          </Button>
        </>
      }
    />
  )
}
