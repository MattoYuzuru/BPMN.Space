import { createRouter, RouterProvider } from '@tanstack/react-router'
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { AppProviders } from '@/app/providers'
import { queryClient } from '@/app/query-client'
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
