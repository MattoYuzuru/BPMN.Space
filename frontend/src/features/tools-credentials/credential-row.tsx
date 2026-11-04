import {
  type Credential,
  credentialErrorLabel,
  isExhausted,
  kindLabel,
  monthlyLimitText,
  providerLabel,
} from '@/entities/tool-credential'
import { formatRelative } from '@/shared/lib/format'
import { TOUR_ANCHORS, tourAnchor } from '@/shared/lib/tour-anchors'
import { Badge, Button, Card, Icon, IconButton, Switch, Tag, Tooltip } from '@/shared/ui'

/** Строка ключа: что закрывает, приоритет, лимит, ошибки; проверка и правка рядом. */
export function CredentialRow({
  credential,
  providers,
  checking,
  onCheck,
  onEdit,
  onToggle,
  onDelete,
}: {
  credential: Credential
  providers: readonly { id: string; label: string }[]
  checking: boolean
  onCheck: () => void
  onEdit: () => void
  onToggle: (enabled: boolean) => void
  onDelete: () => void
}) {
  const error = credentialErrorLabel(credential.last_error_code)
  const limit = monthlyLimitText(credential.monthly_limit)
  const exhausted = isExhausted(credential)
  return (
    <Card variant="outline" padding="sm" className="flex items-start gap-3">
      <Icon name="key" size={20} className="mt-0.5 shrink-0 text-fg-subtle" />
      <div className="flex min-w-0 flex-1 flex-col gap-1">
        <div className="flex min-w-0 flex-wrap items-center gap-2">
          <span className="type-ui font-medium truncate text-fg">{credential.label}</span>
          {credential.is_default && <Badge tone="accent">По умолчанию</Badge>}
          {exhausted && (
            <Badge tone="amber" variant="outline" icon="clock">
              Отдыхает после квоты
            </Badge>
          )}
          {!credential.enabled && (
            <Badge tone="neutral" variant="outline">
              Выключен
            </Badge>
          )}
        </div>
        <div className="type-caption flex flex-wrap items-center gap-x-2 text-fg-muted">
          <span>{providerLabel(providers, credential.provider)}</span>
          <span className="font-mono">{credential.key_hint}</span>
          <Tooltip content="Меньше — раньше в переборе">
            <span {...tourAnchor(TOUR_ANCHORS.toolsPriority)} data-numeric>
              Приоритет {credential.priority}
            </span>
          </Tooltip>
          {credential.last_used_at && (
            <span>использован {formatRelative(new Date(credential.last_used_at))}</span>
          )}
        </div>
        <div className="flex flex-wrap gap-1">
          {credential.kinds.map((kind) => (
            <Tag key={kind} icon="bolt">
              {kindLabel(kind)}
            </Tag>
          ))}
          {limit && <span className="self-center type-caption text-fg-subtle">{limit}</span>}
        </div>
        {(credential.last_error || error) && (
          <p className="type-caption flex items-center gap-1 text-danger-fg">
            <Icon name="alert-triangle" size={14} />
            <span className="truncate">{credential.last_error ?? error}</span>
          </p>
        )}
      </div>
      <div className="flex shrink-0 items-center gap-0.5">
        <Tooltip content={credential.enabled ? 'Выключить ключ' : 'Включить ключ'}>
          <span className="inline-flex">
            <Switch
              checked={credential.enabled}
              aria-label={`${credential.enabled ? 'Выключить' : 'Включить'} ключ «${credential.label}»`}
              onCheckedChange={onToggle}
            />
          </span>
        </Tooltip>
        <Button
          size="sm"
          variant="ghost"
          leadingIcon="refresh"
          loading={checking}
          onClick={onCheck}
        >
          Проверить
        </Button>
        <IconButton
          icon="pencil"
          size="sm"
          label={`Изменить ключ «${credential.label}»`}
          onClick={onEdit}
        />
        <IconButton
          icon="trash"
          size="sm"
          label={`Удалить ключ «${credential.label}»`}
          onClick={onDelete}
        />
      </div>
    </Card>
  )
}
