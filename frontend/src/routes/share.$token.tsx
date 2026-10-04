import { createFileRoute } from '@tanstack/react-router'
import { useCallback } from 'react'
import { sessionQueryOptions } from '@/entities/session'
import { RouteErrorScreen } from '@/widgets/route-states/route-states'
import { SharePage, type SharePageProps } from '@/widgets/share-page/share-page'
import { ShareSkeleton } from '@/widgets/skeletons/screen-skeletons'

const optional = (value: unknown) => (typeof value === 'string' && value ? value : undefined)

/**
 * Публичная страница по ссылке «поделиться». Вне закрытого раздела `_app`: гостя на вход не
 * отправляет, но знает о сессии — вошедшему предлагает принять приглашение или открыть проект.
 * Ответ по ссылке (401, 404, 410 — обычные состояния) разбирает сам экран, а не loader.
 */
export const Route = createFileRoute('/share/$token')({
  validateSearch: (search: Record<string, unknown>): SharePageProps['search'] => ({
    question: optional(search.question),
    source: optional(search.source),
    mark: optional(search.mark),
  }),
  loader: ({ context }) => context.queryClient.ensureQueryData(sessionQueryOptions),
  pendingComponent: ShareSkeleton,
  errorComponent: RouteErrorScreen,
  component: ShareRoute,
})

function ShareRoute() {
  const { token } = Route.useParams()
  const search = Route.useSearch()
  const navigate = Route.useNavigate()
  const onSearchChange = useCallback<SharePageProps['onSearchChange']>(
    (patch, options) =>
      void navigate({
        search: (previous) => ({ ...previous, ...patch }),
        replace: options?.replace,
      }),
    [navigate],
  )
  return <SharePage token={token} search={search} onSearchChange={onSearchChange} />
}
