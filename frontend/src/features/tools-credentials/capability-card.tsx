import {
  type CapabilityCard,
  capabilityInfo,
  capabilityState,
  credentialErrorLabel,
  providersText,
} from '@/entities/tool-credential'
import { Badge, Button, Card, Icon } from '@/shared/ui'

/**
 * Карточка возможности (RFC-0006): сколько ключей её закрывают, какие провайдеры подходят
 * и что делать, если ключа нет.
 */
export function CapabilityCardView({ card, onAdd }: { card: CapabilityCard; onAdd: () => void }) {
  const info = capabilityInfo(card.capability)
  const state = capabilityState(card)
  const error = credentialErrorLabel(card.last_error_code)
  return (
    <Card variant="outline" padding="sm" className="flex items-start gap-3">
      <span className="grid size-8 shrink-0 place-items-center rounded-md border border-border bg-bg-subtle text-fg-muted">
        <Icon name={info.icon} size={16} />
      </span>
      <div className="flex min-w-0 flex-1 flex-col gap-1">
        <div className="flex min-w-0 flex-wrap items-center gap-2">
          <span className="type-ui font-medium truncate text-fg">{card.label || info.label}</span>
          {state === 'ready' ? (
            <Badge tone="success" icon="circle-check">
              {card.keys === 1 ? '1 ключ' : `${card.keys} ключа`}
            </Badge>
          ) : state === 'error' ? (
            <Badge tone="danger" variant="outline" icon="alert-triangle">
              {error ?? 'Ошибка'}
            </Badge>
          ) : (
            <Badge tone="amber" variant="outline" icon="key">
              Нужен ключ
            </Badge>
          )}
        </div>
        <p className="type-caption text-fg-muted">{card.description || info.description}</p>
        {card.providers.length > 0 && (
          <p className="type-caption text-fg-subtle">Ключи: {providersText(card.providers)}</p>
        )}
      </div>
      <Button size="sm" variant="ghost" leadingIcon="plus" onClick={onAdd}>
        Добавить
      </Button>
    </Card>
  )
}
