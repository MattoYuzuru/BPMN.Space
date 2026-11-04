import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { type AgentActivityEvent, agentActivityQueryOptions } from '@/entities/project'
import { errorMessage } from '@/shared/api/client'
import { formatDate, formatRelative, formatTime } from '@/shared/lib/format'
import {
  Badge,
  Button,
  Card,
  EmptyState,
  IconButton,
  Sheet,
  SheetContent,
  Skeleton,
  Tag,
  Tooltip,
} from '@/shared/ui'

/** Заголовок события: что именно сделал агент. */
export function agentActivityTitle(event: AgentActivityEvent): string {
  if (event.kind === 'source_added') return 'Источник добавлен агентом'
  if (event.kind === 'answer_added') return 'Ответ дан агентом'
  return event.title || 'Событие агента'
}

/** Уточнение события: название материала или код вопроса. */
export function agentActivitySubject(event: AgentActivityEvent): string | null {
  if (event.kind === 'source_added') return event.title ? `«${event.title}»` : null
  if (event.kind === 'answer_added')
    return event.question_code ? `Вопрос ${event.question_code}` : null
  return null
}

const KIND_BADGE = {
  source_added: { label: 'Источник', icon: 'file-text' as const },
  answer_added: { label: 'Ответ', icon: 'message-question' as const },
}

/**
 * Кнопка журнала в шапке проекта: что агент добавил или ответил. Журнал собирается сервером
 * из источников с `origin=agent` и ответов с `answer.via=agent` — отдельной ленты событий нет.
 */
export function AgentActivityButton({ projectId }: { projectId: string }) {
  const [open, setOpen] = useState(false)
  return (
    <>
      <Tooltip content="Что делал агент в проекте" side="bottom">
        <IconButton
          icon="sparkles"
          size="sm"
          label="Активность агента"
          tooltip={false}
          onClick={() => setOpen(true)}
        />
      </Tooltip>
      <AgentActivitySheet projectId={projectId} open={open} onOpenChange={setOpen} />
    </>
  )
}

/** Боковая панель журнала: события, имя токена, время и пустое состояние. */
export function AgentActivitySheet({
  projectId,
  open,
  onOpenChange,
}: {
  projectId: string
  open: boolean
  onOpenChange: (open: boolean) => void
}) {
  const activity = useQuery({ ...agentActivityQueryOptions(projectId), enabled: open })
  const items = activity.data?.items ?? []

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent
        size="md"
        title="Активность агента"
        description="Материалы и ответы, которые агент оставил в этом проекте."
      >
        {activity.isPending && (
          <div className="flex flex-col gap-2" aria-busy="true">
            <Skeleton className="h-16 w-full rounded-md" />
            <Skeleton className="h-16 w-full rounded-md" />
          </div>
        )}
        {activity.isError && (
          <EmptyState
            size="sm"
            backdrop="none"
            icon="alert-circle"
            title="Журнал не загрузился"
            description={errorMessage(activity.error)}
            action={<Button onClick={() => void activity.refetch()}>Повторить</Button>}
          />
        )}
        {activity.data && items.length === 0 && (
          <EmptyState
            size="sm"
            backdrop="none"
            icon="sparkles"
            title="Агент пока ничего не делал"
            description="Здесь появятся материалы и ответы, которые агент добавит в проект."
          />
        )}
        {items.length > 0 && (
          <ul className="flex flex-col gap-2" aria-label="События агента">
            {items.map((event) => (
              <li
                key={`${event.kind}-${event.at}-${event.token_name ?? ''}-${event.question_id ?? event.source_id ?? ''}`}
              >
                <EventCard event={event} />
              </li>
            ))}
          </ul>
        )}
      </SheetContent>
    </Sheet>
  )
}

function EventCard({ event }: { event: AgentActivityEvent }) {
  const badge = KIND_BADGE[event.kind as keyof typeof KIND_BADGE]
  const at = new Date(event.at)
  return (
    <Card variant="outline" padding="sm" className="flex items-start gap-3">
      <div className="flex min-w-0 flex-1 flex-col gap-1.5">
        <div className="flex flex-wrap items-center gap-2">
          <Badge tone="accent" variant="outline" icon={badge?.icon ?? 'sparkles'}>
            {badge?.label ?? 'Событие'}
          </Badge>
          {event.token_name && <Tag icon="key">{event.token_name}</Tag>}
          {event.share_link_id && (
            <Badge tone="neutral" variant="outline">
              По ссылке проверки
            </Badge>
          )}
        </div>
        <span className="type-ui text-fg">{agentActivityTitle(event)}</span>
        {agentActivitySubject(event) && (
          <span className="type-ui text-fg-muted">{agentActivitySubject(event)}</span>
        )}
        {event.detail && <p className="line-clamp-3 type-caption text-fg-muted">{event.detail}</p>}
        <Tooltip content={`${formatDate(at)}, ${formatTime(at)}`}>
          <span className="w-fit type-caption text-fg-subtle">{formatRelative(at)}</span>
        </Tooltip>
      </div>
    </Card>
  )
}
