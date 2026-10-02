import { createFileRoute } from '@tanstack/react-router'
import { useCallback } from 'react'
import { projectQueryOptions } from '@/entities/project'
import { versionDetailOptions } from '@/entities/version'
import { preloadDiagramEditor } from '@/widgets/diagram-editor'
import { RouteErrorScreen } from '@/widgets/route-states/route-states'
import { WorkspaceSkeleton } from '@/widgets/skeletons/screen-skeletons'
import { Workspace, type WorkspaceSearch } from '@/widgets/workspace/workspace'

const optional = (value: unknown) => (typeof value === 'string' && value ? value : undefined)

/**
 * Рабочее место проекта. Loader параллельно грузит проект, XML последней версии и чанк
 * редактора bpmn-js — к моменту показа схема уже готова к отрисовке. При наведении на ссылку
 * проекта (preload: intent) всё это начинается заранее.
 */
export const Route = createFileRoute('/projects/$projectId')({
  validateSearch: (search: Record<string, unknown>): WorkspaceSearch => ({
    question: optional(search.question),
    version: optional(search.version),
    source: optional(search.source),
    mark: optional(search.mark),
  }),
  loader: async ({ context: { queryClient }, params }) => {
    void preloadDiagramEditor()
    const project = await queryClient.ensureQueryData(projectQueryOptions(params.projectId))
    if (project.latest_version) {
      await queryClient.prefetchQuery(versionDetailOptions(project.latest_version.id))
    }
  },
  pendingComponent: WorkspaceSkeleton,
  errorComponent: RouteErrorScreen,
  component: WorkspaceRoute,
})

function WorkspaceRoute() {
  const { projectId } = Route.useParams()
  const search = Route.useSearch()
  const navigate = Route.useNavigate()
  const onSearchChange = useCallback(
    (patch: Partial<WorkspaceSearch>, options?: { replace?: boolean }) =>
      void navigate({
        search: (previous) => ({ ...previous, ...patch }),
        replace: options?.replace,
      }),
    [navigate],
  )
  return <Workspace projectId={projectId} search={search} onSearchChange={onSearchChange} />
}
