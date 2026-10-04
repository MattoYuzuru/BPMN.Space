import type { QueryClient } from '@tanstack/react-query'
import {
  createRootRouteWithContext,
  type ErrorComponentProps,
  Outlet,
  useMatch,
} from '@tanstack/react-router'
import { lazy, Suspense } from 'react'
import { CommandCenter } from '@/features/command-palette/command-center'
import { useCreateProjectDialog } from '@/features/create-project/model'

// Корень входит в стартовый бандл, поэтому всё, что нужно не сразу, грузится лениво:
// диалог создания проекта — при первом открытии, экраны 404 и ошибки — когда они понадобились.
const CreateProjectDialog = lazy(() =>
  import('@/features/create-project/create-project-dialog').then((module) => ({
    default: module.CreateProjectDialog,
  })),
)
const NotFoundScreen = lazy(() =>
  import('@/widgets/route-states/route-states').then((module) => ({
    default: module.NotFoundScreen,
  })),
)
const RouteErrorScreen = lazy(() =>
  import('@/widgets/route-states/route-states').then((module) => ({
    default: module.RouteErrorScreen,
  })),
)

export const Route = createRootRouteWithContext<{ queryClient: QueryClient }>()({
  component: RootLayout,
  notFoundComponent: () => (
    <Suspense fallback={null}>
      <NotFoundScreen />
    </Suspense>
  ),
  errorComponent: (props: ErrorComponentProps) => (
    <Suspense fallback={null}>
      <RouteErrorScreen {...props} />
    </Suspense>
  ),
})

/** Корень: экран маршрута и глобальные слои — палитра команд и создание проекта (кроме входа). */
function RootLayout() {
  const onLogin = useMatch({ from: '/login', shouldThrow: false })
  const createRequested = useCreateProjectDialog((state) => state.open || state.loaded)
  return (
    <>
      <Outlet />
      {!onLogin && <CommandCenter />}
      {!onLogin && createRequested && (
        <Suspense fallback={null}>
          <CreateProjectDialog />
        </Suspense>
      )}
    </>
  )
}
