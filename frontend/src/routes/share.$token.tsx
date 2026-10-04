import { createFileRoute } from '@tanstack/react-router'
import { useCallback } from 'react'
import { sessionQueryOptions } from '@/entities/session'
import { useDocumentMeta } from '@/shared/hooks/use-document-meta'
import { RouteErrorScreen } from '@/widgets/route-states/route-states'
import { SharePage, type SharePageProps } from '@/widgets/share-page/share-page'
import { WorkspaceSkeleton } from '@/widgets/skeletons/screen-skeletons'

const optional = (value: unknown) => (typeof value === 'string' && value ? value : undefined)

/**
 * Публичная страница по ссылке «поделиться». Вне закрытого раздела `_app`: гостя на вход не
 * отправляет, но знает о сессии — вошедшему предлагает принять приглашение или открыть проект.
 * Пока ответ по ссылке не пришёл, роль неизвестна, поэтому ожидание нейтральное — скелетон
 * рабочего места; карточка приглашения показывает своё состояние проверки сама.
 * Ответ по ссылке (401, 404, 410 — обычные состояния) разбирает сам экран, а не loader.
 */
export const Route = createFileRoute('/share/$token')({
  validateSearch: (search: Record<string, unknown>): SharePageProps['search'] => ({
    question: optional(search.question),
    source: optional(search.source),
    mark: optional(search.mark),
  }),
  loader: ({ context }) => context.queryClient.ensureQueryData(sessionQueryOptions),
  pendingComponent: WorkspaceSkeleton,
  errorComponent: RouteErrorScreen,
  component: ShareRoute,
})

function ShareRoute() {
  // Секрет в адресе: не отдаём его во внешние запросы (Referer) и просим не индексировать.
  useDocumentMeta('referrer', 'no-referrer')
  useDocumentMeta('robots', 'noindex')
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
