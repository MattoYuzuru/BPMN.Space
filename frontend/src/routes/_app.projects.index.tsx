import { createFileRoute } from '@tanstack/react-router'
import {
  type ProjectScope,
  projectsInfiniteOptions,
  scopeFromSearch,
  scopeToSearch,
} from '@/entities/project'
import { ProjectsScreen } from '@/widgets/projects-grid/projects-screen'
import { ProjectsScreenSkeleton } from '@/widgets/skeletons/screen-skeletons'

interface ProjectsSearch {
  q?: string
  /** Область списка: свои, общие, примеры; «все» в адрес не пишется. */
  scope?: Exclude<ProjectScope, 'all'>
}

/** Список проектов доступен из главной страницы и загружается сразу с первой страницей данных. */
export const Route = createFileRoute('/_app/projects/')({
  validateSearch: (search: Record<string, unknown>): ProjectsSearch => ({
    q: typeof search.q === 'string' && search.q.trim() ? search.q : undefined,
    scope: scopeToSearch(scopeFromSearch(search.scope)),
  }),
  loaderDeps: ({ search }) => ({ q: search.q ?? '', scope: scopeFromSearch(search.scope) }),
  loader: ({ context, deps }) =>
    context.queryClient.ensureInfiniteQueryData(projectsInfiniteOptions(deps.q, deps.scope)),
  pendingComponent: ProjectsScreenSkeleton,
  component: ProjectsRoute,
})

function ProjectsRoute() {
  const { q = '', scope } = Route.useSearch()
  const navigate = Route.useNavigate()
  return (
    <ProjectsScreen
      query={q}
      scope={scopeFromSearch(scope)}
      onQueryChange={(next) =>
        void navigate({
          search: (previous) => ({ ...previous, q: next || undefined }),
          replace: true,
        })
      }
      onScopeChange={(next) =>
        void navigate({ search: (previous) => ({ ...previous, scope: scopeToSearch(next) }) })
      }
    />
  )
}
