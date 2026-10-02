import { createFileRoute } from '@tanstack/react-router'
import { projectsInfiniteOptions } from '@/entities/project'
import { ProjectsScreen, ProjectsScreenSkeleton } from '@/widgets/projects-grid/projects-screen'

interface ProjectsSearch {
  q?: string
}

/** Список проектов. Первая страница грузится в loader — экран появляется уже с данными. */
export const Route = createFileRoute('/')({
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
