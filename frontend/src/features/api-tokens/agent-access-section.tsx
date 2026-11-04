import { useRef, useState } from 'react'
import {
  type ApiToken,
  scopeLabel,
  type TokenProjectChoice,
  useApiTokens,
  useRevokeApiToken,
  useTokenProjectChoices,
} from '@/entities/api-token'
import { useOnboardingUi } from '@/entities/onboarding'
import { formatCount, formatDate, formatRelative } from '@/shared/lib/format'
import { TOUR_ANCHORS, tourAnchor } from '@/shared/lib/tour-anchors'
import {
  Badge,
  Button,
  Card,
  ConfirmDialog,
  EmptyState,
  Icon,
  IconButton,
  Skeleton,
  Tag,
} from '@/shared/ui'
import { CreateTokenDialog } from './create-token-dialog'

/** Раздел «Доступ для агентов»: персональные токены для Claude Code и других клиентов (RFC-0007). */
export function AgentAccessSection() {
  const tokens = useApiTokens()
  const projects = useTokenProjectChoices()
  const revoke = useRevokeApiToken()
  const openAgentTour = useOnboardingUi((state) => state.openAgentTour)
  const [creating, setCreating] = useState(false)
  const [revoking, setRevoking] = useState<ApiToken | null>(null)
  const titleRef = useRef<HTMLHeadingElement>(null)
  const revokedRef = useRef(false)
  const items = tokens.data ?? []

  return (
    <section
      aria-labelledby="agents-title"
      className="flex flex-col gap-4"
      {...tourAnchor(TOUR_ANCHORS.agentTokens)}
    >
      <div className="flex items-center gap-3">
        <h2
          id="agents-title"
          ref={titleRef}
          tabIndex={-1}
          className="type-heading flex-1 text-fg outline-none"
        >
          Доступ для агентов
        </h2>
        <Button leadingIcon="help" size="sm" onClick={openAgentTour}>
          Как подключить
        </Button>
        <Button
          leadingIcon="plus"
          size="sm"
          variant="primary"
          onClick={() => setCreating(true)}
          {...tourAnchor(TOUR_ANCHORS.agentCreateToken)}
        >
          Создать токен
        </Button>
      </div>
      <p className="type-ui text-fg-muted">
        Токен позволяет вашему агенту, например Claude Code, работать с проектами от вашего имени:
        читать схему, отвечать на вопросы, добавлять материалы.
      </p>

      {tokens.isPending && <Skeleton className="h-16 w-full" />}
      {tokens.isError && (
        <p role="alert" className="type-ui text-danger-fg">
          Не удалось загрузить токены.
        </p>
      )}
      {tokens.data && items.length === 0 && (
        <Card variant="sunken" padding="none">
          <EmptyState
            icon="key"
            size="sm"
            backdrop="none"
            title="Токенов нет"
            description="Агенты пока не подключены."
            action={<Button onClick={openAgentTour}>Как подключить агента</Button>}
          />
        </Card>
      )}
      <ul className="flex flex-col gap-2">
        {items.map((item) => (
          <li key={item.id}>
            <TokenRow token={item} projects={projects.data} onRevoke={() => setRevoking(item)} />
          </li>
        ))}
      </ul>

      <CreateTokenDialog open={creating} onOpenChange={setCreating} />
      <ConfirmDialog
        open={revoking !== null}
        onOpenChange={(open) => {
          if (open) return
          setRevoking(null)
          // Строка отозванного токена исчезла: фокус — на заголовок раздела.
          if (revokedRef.current) {
            revokedRef.current = false
            window.setTimeout(() => titleRef.current?.focus(), 100)
          }
        }}
        title={`Отозвать токен «${revoking?.name ?? ''}»?`}
        description="Агенты с этим токеном сразу потеряют доступ. Вернуть токен нельзя, только создать новый."
        confirmLabel="Отозвать"
        tone="danger"
        onConfirm={async () => {
          if (!revoking) return
          await revoke.mutateAsync(revoking.id)
          revokedRef.current = true
        }}
      />
    </section>
  )
}

const PROJECT_FORMS = ['проект', 'проекта', 'проектов'] as const

/** «Все проекты», «Договоры» или «3 проекта» — названия берём из уже загруженного списка. */
export function projectsSummary(
  ids: readonly string[] | null,
  projects: readonly TokenProjectChoice[] | undefined,
): string {
  if (ids === null) return 'Все проекты'
  const titles = ids
    .map((id) => projects?.find((project) => project.id === id)?.title)
    .filter((title): title is string => Boolean(title))
  if (titles.length === ids.length && titles.length > 0 && titles.length <= 2) {
    return titles.map((title) => `«${title}»`).join(', ')
  }
  return formatCount(ids.length, PROJECT_FORMS)
}

/** Строка токена: название, префикс, права, проекты, срок и последнее использование. */
export function TokenRow({
  token,
  projects,
  onRevoke,
}: {
  token: ApiToken
  projects: readonly TokenProjectChoice[] | undefined
  onRevoke: () => void
}) {
  return (
    <Card variant="outline" padding="sm" className="flex items-start gap-3">
      <Icon name="key" size={20} className="mt-0.5 shrink-0 text-fg-subtle" />
      <div className="flex min-w-0 flex-1 flex-col gap-1">
        <div className="flex min-w-0 items-center gap-2">
          <span className="type-ui font-medium truncate text-fg">{token.name}</span>
          {token.expired && <Badge tone="danger">Истёк</Badge>}
        </div>
        <div className="type-caption flex flex-wrap items-center gap-x-2 text-fg-muted">
          <span className="font-mono">{token.token_prefix}</span>
          <span>{projectsSummary(token.project_ids, projects)}</span>
          {!token.expired && <span>до {formatDate(new Date(token.expires_at))}</span>}
          <span>
            {token.last_used_at
              ? `использован ${formatRelative(new Date(token.last_used_at))}`
              : 'не использовался'}
          </span>
        </div>
        <div className="flex flex-wrap gap-1">
          {token.scopes.map((scope) => (
            <Tag key={scope}>{scopeLabel(scope)}</Tag>
          ))}
        </div>
      </div>
      <IconButton
        icon="trash"
        size="sm"
        label={`Отозвать токен «${token.name}»`}
        onClick={onRevoke}
      />
    </Card>
  )
}
