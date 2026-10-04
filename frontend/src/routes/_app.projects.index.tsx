import { createFileRoute } from '@tanstack/react-router'
import { projectsInfiniteOptions } from '@/entities/project'
import { ProjectsScreen } from '@/widgets/projects-grid/projects-screen'
import { ProjectsScreenSkeleton } from '@/widgets/skeletons/screen-skeletons'

interface ProjectsSearch {
  q?: string
}

/** Список проектов доступен из главной страницы и загружается сразу с первой страницей данных. */
export const Route = createFileRoute('/_app/projects/')({
  validateSearch: (search: Record<string, unknown>): ProjectsSearch => ({
    q: typeof search.q === 'string' && search.q.trim() ? search.q : undefined,
  }),
  loaderDeps: ({ search }) => ({ q: search.q ?? '' }),
  loader: ({ context, deps }) =>
    context.queryClient.ensureInfiniteQueryData(projectsInfiniteOptions(deps.q)),
  pendingComponent: ProjectsScreenSkeleton,
  component: ProjectsRoute,
})

function ProjectsRoute() {
  const { q = '' } = Route.useSearch()
  const navigate = Route.useNavigate()
  return (
    <ProjectsScreen
      query={q}
      onQueryChange={(next) => void navigate({ search: { q: next || undefined }, replace: true })}
    />
  )
}
