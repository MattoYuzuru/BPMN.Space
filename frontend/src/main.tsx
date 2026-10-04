import { createRouter, RouterProvider } from '@tanstack/react-router'
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { AppProviders } from '@/app/providers'
import { queryClient, setUnauthorizedHandler } from '@/app/query-client'
import { handleUnauthorized } from '@/app/session-expiry'
import { routeTree } from './routeTree.gen'
// Шрифты Geist и Geist Mono — локальные файлы, кириллица включена. Без внешних CDN.
import '@fontsource-variable/geist'
import '@fontsource-variable/geist-mono'
import '@/shared/styles/index.css'

const router = createRouter({
  routeTree,
  context: { queryClient },
  // Код и данные маршрута начинают грузиться при наведении на ссылку.
  defaultPreload: 'intent',
  defaultPreloadStaleTime: 0,
  scrollRestoration: true,
})

// Сессия закончилась посреди работы (401): перечитываем состояние и уходим на вход.
setUnauthorizedHandler(
  () =>
    void handleUnauthorized({
      client: queryClient,
      isProtected: () => router.state.matches.some((match) => match.routeId.startsWith('/_app')),
      currentHref: () => router.state.location.href,
      toLogin: (search) => router.navigate({ to: '/login', search, replace: true }),
    }),
)

declare module '@tanstack/react-router' {
  interface Register {
    router: typeof router
  }
}

const root = document.getElementById('root')
if (!root) throw new Error('Не найден #root')

createRoot(root).render(
  <StrictMode>
    <AppProviders>
      <RouterProvider router={router} />
    </AppProviders>
  </StrictMode>,
)
