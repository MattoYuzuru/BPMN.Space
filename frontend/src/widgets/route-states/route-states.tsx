import { useQueryErrorResetBoundary } from '@tanstack/react-query'
import { type ErrorComponentProps, Link, useRouter } from '@tanstack/react-router'
import { useEffect } from 'react'
import { ApiError } from '@/shared/api/client'
import { BrandMark, Button, EmptyState, GridBackdrop } from '@/shared/ui'
import { AppHeader } from '@/widgets/app-header/app-header'

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
