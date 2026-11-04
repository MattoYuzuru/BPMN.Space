import { type UseQueryResult, useQuery } from '@tanstack/react-query'
import { useEffect, useRef, useState } from 'react'
import { projectQueryOptions } from '@/entities/project'
import {
  activeLinks,
  type ProjectMember,
  projectMembersQueryOptions,
  type ShareLink,
  type ShareLinkCreated,
  shareLinksQueryOptions,
  useCreateShareLink,
  useRemoveMember,
  useRevokeShareLink,
} from '@/entities/share'
import { errorMessage } from '@/shared/api/client'
import {
  Button,
  Dialog,
  DialogContent,
  Divider,
  EmptyState,
  Skeleton,
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
} from '@/shared/ui'
import { fullShareUrl, useShareDialogControl, useShareForm } from './model'
import { MemberRow, ShareCreateForm, ShareLinkResult, ShareLinkRow } from './share-parts'

export interface ShareDialogProps {
  projectId: string
  open: boolean
  onOpenChange: (open: boolean) => void
}

/**
 * Диалог доступа к проекту (только владелец): создать ссылку, посмотреть действующие, отозвать,
 * убрать участников. Содержимое монтируется на время показа, поэтому показанный адрес ссылки
 * исчезает вместе с закрытием окна и нигде не хранится.
 */
export function ShareDialog({ projectId, open, onOpenChange }: ShareDialogProps) {
  const closeRequest = useShareDialogControl((state) => state.closeRequest)
  const seen = useRef(closeRequest)
  // biome-ignore lint/correctness/useExhaustiveDependencies: реагируем только на новую просьбу закрыть
  useEffect(() => {
    if (closeRequest !== seen.current) {
      seen.current = closeRequest
      onOpenChange(false)
    }
  }, [closeRequest])
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent title="Поделиться проектом" size="md">
        <ShareDialogBody projectId={projectId} />
      </DialogContent>
    </Dialog>
  )
}

function ShareDialogBody({ projectId }: { projectId: string }) {
  const form = useShareForm()
  const create = useCreateShareLink(projectId)
  const [created, setCreated] = useState<ShareLinkCreated | null>(null)
  // Адрес ссылки сервер отдаёт один раз; пока окно открыто, его можно скопировать и из списка.
  const [createdUrls, setCreatedUrls] = useState<Record<string, string>>({})
  // Дорожки нужны только проверке: у просмотра и редактирования области нет.
  const project = useQuery({
    ...projectQueryOptions(projectId),
    enabled: form.role === 'reviewer' && !created,
  })
  const lanes = project.data?.lanes ?? []
  const selectedLanes = form.scope === 'selected' ? form.lanes : []

  const submit = () =>
    create.mutate(
      {
        role: form.role,
        days: form.days,
        laneIds: form.role === 'reviewer' ? selectedLanes : undefined,
      },
      {
        onSuccess: (link) => {
          setCreated(link)
          setCreatedUrls((current) => ({
            ...current,
            [link.id]: fullShareUrl(link.url_path),
          }))
        },
      },
    )

  return (
    <div className="flex flex-col gap-5">
      {created ? (
        <ShareLinkResult
          url={fullShareUrl(created.url_path)}
          access={created.role}
          expiresAt={created.expires_at}
          laneIds={created.lane_ids}
          onAnother={() => setCreated(null)}
        />
      ) : (
        <ShareCreateForm
          role={form.role}
          days={form.days}
          scope={form.scope}
          lanes={lanes}
          selectedLanes={selectedLanes}
          onRoleChange={form.setRole}
          onDaysChange={form.setDays}
          onScopeChange={form.setScope}
          onLanesChange={form.setLanes}
          onCreate={submit}
          pending={create.isPending}
          lanesLoading={form.role === 'reviewer' && (project.isPending || project.isFetching)}
          lanesError={form.role === 'reviewer' && project.isError}
        />
      )}
      <Divider />
      <AccessLists projectId={projectId} createdUrls={createdUrls} />
    </div>
  )
}

/** Действующие ссылки и участники — две вкладки со счётчиками. */
function AccessLists({
  projectId,
  createdUrls,
}: {
  projectId: string
  createdUrls: Record<string, string>
}) {
  const links = useQuery(shareLinksQueryOptions(projectId))
  const members = useQuery(projectMembersQueryOptions(projectId))
  const active = activeLinks(links.data ?? [])

  return (
    <Tabs defaultValue="links">
      <TabsList>
        <TabsTrigger value="links" count={links.data ? active.length : undefined}>
          Ссылки
        </TabsTrigger>
        <TabsTrigger value="members" count={members.data?.length}>
          Участники
        </TabsTrigger>
      </TabsList>
      <TabsContent value="links" className="pt-2">
        <LinksList projectId={projectId} query={links} active={active} createdUrls={createdUrls} />
      </TabsContent>
      <TabsContent value="members" className="pt-2">
        <MembersList projectId={projectId} query={members} />
      </TabsContent>
    </Tabs>
  )
}

function ListSkeleton() {
  return (
    <div className="flex flex-col gap-3 py-2" aria-busy="true">
      <Skeleton className="h-9 rounded-md" />
      <Skeleton className="h-9 rounded-md" />
    </div>
  )
}

function ListError({ error, onRetry }: { error: unknown; onRetry: () => void }) {
  return (
    <EmptyState
      size="sm"
      backdrop="none"
      icon="alert-circle"
      title="Список не загрузился"
      description={errorMessage(error)}
      action={<Button onClick={onRetry}>Повторить</Button>}
    />
  )
}

function LinksList({
  projectId,
  query,
  active,
  createdUrls,
}: {
  projectId: string
  query: UseQueryResult<ShareLink[]>
  active: ShareLink[]
  createdUrls: Record<string, string>
}) {
  const revoke = useRevokeShareLink(projectId)
  if (query.isPending) return <ListSkeleton />
  if (query.isError) return <ListError error={query.error} onRetry={() => void query.refetch()} />
  if (active.length === 0) {
    return <EmptyState size="sm" backdrop="none" icon="link" title="Ссылок пока нет" />
  }
  return (
    <ul aria-label="Действующие ссылки" className="flex flex-col divide-y divide-border">
      {active.map((link) => (
        <ShareLinkRow
          key={link.id}
          link={link}
          copyUrl={createdUrls[link.id]}
          onRevoke={() => revoke.mutate(link.id)}
        />
      ))}
    </ul>
  )
}

function MembersList({
  projectId,
  query,
}: {
  projectId: string
  query: UseQueryResult<ProjectMember[]>
}) {
  const remove = useRemoveMember(projectId)
  if (query.isPending) return <ListSkeleton />
  if (query.isError) return <ListError error={query.error} onRetry={() => void query.refetch()} />
  if (!query.data || query.data.length === 0) {
    return <EmptyState size="sm" backdrop="none" icon="users" title="Участников пока нет" />
  }
  return (
    <ul aria-label="Участники" className="flex flex-col divide-y divide-border">
      {query.data.map((member) => (
        <MemberRow
          key={member.user_id}
          member={member}
          onRemove={() => remove.mutate(member.user_id)}
        />
      ))}
    </ul>
  )
}
