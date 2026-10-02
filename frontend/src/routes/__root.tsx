import type { QueryClient } from '@tanstack/react-query'
import { createRootRouteWithContext, Outlet } from '@tanstack/react-router'
import { CommandCenter } from '@/features/command-palette/command-center'
import { CreateProjectDialog } from '@/features/create-project/create-project-dialog'
import { NotFoundScreen, RouteErrorScreen } from '@/widgets/route-states/route-states'

export const Route = createRootRouteWithContext<{ queryClient: QueryClient }>()({
  component: RootLayout,
  notFoundComponent: NotFoundScreen,
  errorComponent: RouteErrorScreen,
})

/** Корень: экран маршрута и глобальные слои — палитра команд и создание проекта. */
function RootLayout() {
  return (
    <>
      <Outlet />
      <CommandCenter />
      <CreateProjectDialog />
    </>
  )
}
