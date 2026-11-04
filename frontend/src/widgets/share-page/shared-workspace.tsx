import { useMemo } from 'react'
import { type SharedProject, shareVersionSource } from '@/entities/share'
import { ReviewInvite } from '@/features/share-reviewer/review-invite'
import { WorkspaceView, type WorkspaceViewProps } from '@/widgets/workspace/workspace'
import { SharedHeader } from './shared-header'

export type SharedWorkspaceSearch = Omit<WorkspaceViewProps['search'], 'version'>

/**
 * Публичный просмотр проекта по ссылке: то же рабочее место, что у владельца, но данные
 * приходят из ответа по ссылке (`SharedProject.detail`), версии — из `shareVersionSource`,
 * а права — только чтение. Правок, прогонов и истории версий здесь нет.
 *
 * У ссылки проверки над рабочим местом стоит полоса «Проверка»: область словами, готовый
 * запрос для агента и подключение своего агента.
 */
export function SharedWorkspace({
  token,
  shared,
  openProject,
  search,
  onSearchChange,
}: {
  token: string
  shared: SharedProject
  openProject: boolean
  search: SharedWorkspaceSearch
  onSearchChange: WorkspaceViewProps['onSearchChange']
}) {
  const versions = useMemo(() => shareVersionSource(token, shared.detail), [token, shared.detail])
  return (
    <WorkspaceView
      project={shared.detail}
      versions={versions}
      readOnly
      collaborationShareToken={token}
      commands={false}
      header={
        <>
          <SharedHeader
            loginRedirect={`/share/${token}`}
            openProject={openProject}
            role={shared.role}
          />
          {shared.role === 'reviewer' && <ReviewInvite token={token} shared={shared} />}
        </>
      }
      search={search}
      onSearchChange={onSearchChange}
    />
  )
}
