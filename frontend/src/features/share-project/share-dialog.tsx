import { type UseQueryResult, useQuery } from '@tanstack/react-query'
import { useState } from 'react'
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
import { fullShareUrl, useShareForm } from './model'
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

  const submit = () =>
    create.mutate({ role: form.role, days: form.days }, { onSuccess: (link) => setCreated(link) })

  return (
    <div className="flex flex-col gap-5">
      {created ? (
        <ShareLinkResult
          url={fullShareUrl(created.url_path)}
          access={created.role}
          expiresAt={created.expires_at}
          onAnother={() => setCreated(null)}
        />
      ) : (
        <ShareCreateForm
          role={form.role}
          days={form.days}
          onRoleChange={form.setRole}
          onDaysChange={form.setDays}
          onCreate={submit}
          pending={create.isPending}
        />
      )}
      <Divider />
      <AccessLists projectId={projectId} />
    </div>
  )
}

/** Действующие ссылки и участники — две вкладки со счётчиками. */
function AccessLists({ projectId }: { projectId: string }) {
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
        <LinksList projectId={projectId} query={links} active={active} />
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
}: {
  projectId: string
  query: UseQueryResult<ShareLink[]>
  active: ShareLink[]
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
        <ShareLinkRow key={link.id} link={link} onRevoke={() => revoke.mutate(link.id)} />
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
