import { useState } from 'react'
import {
  keyMask,
  type LlmCredential,
  modelLabel,
  providerLabel,
  useDeleteLlmCredential,
  useLlmCredentials,
} from '@/entities/llm-credential'
import { formatRelative } from '@/shared/lib/format'
import {
  Badge,
  Button,
  Card,
  ConfirmDialog,
  EmptyState,
  Icon,
  IconButton,
  Skeleton,
} from '@/shared/ui'
import { AddCredentialDialog } from './add-credential-dialog'
import { EditCredentialDialog } from './edit-credential-dialog'

/** Раздел «Модели и ключи»: свои ключи провайдеров, модель по умолчанию, последняя ошибка. */
export function CredentialsSection() {
  const credentials = useLlmCredentials()
  const remove = useDeleteLlmCredential()
  const [adding, setAdding] = useState(false)
  const [editing, setEditing] = useState<LlmCredential | null>(null)
  const [deleting, setDeleting] = useState<LlmCredential | null>(null)
  const storage = credentials.data?.storage_available ?? true
  const items = credentials.data?.items ?? []

  return (
    <section aria-labelledby="models-title" className="flex flex-col gap-4">
      <div className="flex items-center gap-3">
        <h2 id="models-title" className="type-heading flex-1 text-fg">
          Модели и ключи
        </h2>
        <Button
          leadingIcon="plus"
          size="sm"
          variant="primary"
          disabled={!storage}
          onClick={() => setAdding(true)}
        >
          Добавить ключ
        </Button>
      </div>

      {credentials.isPending && <Skeleton className="h-16 w-full" />}
      {credentials.isError && (
        <p role="alert" className="type-ui text-danger-fg">
          Не удалось загрузить ключи.
        </p>
      )}
      {!storage && (
        <Card variant="sunken" padding="sm" className="flex items-center gap-2">
          <Icon name="alert-triangle" size={16} className="text-amber-fg" />
          <span className="type-ui text-fg-muted">
            Хранение ключей не настроено на сервере. Используется модель сервера.
          </span>
        </Card>
      )}
      {credentials.data && items.length === 0 && storage && (
        <Card variant="sunken" padding="none">
          <EmptyState
            icon="key"
            size="sm"
            backdrop="none"
            title="Своих ключей нет"
            description="Используется модель сервера."
          />
        </Card>
      )}
      <ul className="flex flex-col gap-2">
        {items.map((item) => (
          <li key={item.id}>
            <CredentialRow
              credential={item}
              onEdit={() => setEditing(item)}
              onDelete={() => setDeleting(item)}
            />
          </li>
        ))}
      </ul>

      <AddCredentialDialog open={adding} onOpenChange={setAdding} />
      <EditCredentialDialog credential={editing} onClose={() => setEditing(null)} />
      <ConfirmDialog
        open={deleting !== null}
        onOpenChange={(open) => !open && setDeleting(null)}
        title={`Удалить ключ «${deleting?.label ?? ''}»?`}
        description="Ключ стирается с сервера. Прогоны, которые идут с ним сейчас, завершатся ошибкой."
        confirmLabel="Удалить"
        tone="danger"
        onConfirm={async () => {
          if (deleting) await remove.mutateAsync(deleting.id)
        }}
      />
    </section>
  )
}

/** Строка ключа: название, подсказка, модель; ошибка последнего использования видна сразу. */
export function CredentialRow({
  credential,
  onEdit,
  onDelete,
}: {
  credential: LlmCredential
  onEdit: () => void
  onDelete: () => void
}) {
  return (
    <Card variant="outline" padding="sm" className="flex items-center gap-3">
      <Icon name="key" size={20} className="shrink-0 text-fg-subtle" />
      <div className="flex min-w-0 flex-1 flex-col gap-0.5">
        <div className="flex min-w-0 items-center gap-2">
          <span className="type-ui-strong truncate text-fg">{credential.label}</span>
          {credential.is_default && <Badge tone="accent">По умолчанию</Badge>}
        </div>
        <div className="type-caption flex flex-wrap items-center gap-x-2 text-fg-muted">
          <span>{providerLabel(credential.provider)}</span>
          <span data-numeric>{keyMask(credential.key_hint)}</span>
          {credential.default_model && <span>{modelLabel(credential.default_model)}</span>}
          {credential.last_used_at && (
            <span>использован {formatRelative(new Date(credential.last_used_at))}</span>
          )}
        </div>
        {credential.last_error && (
          <p className="type-caption flex items-center gap-1 text-danger-fg">
            <Icon name="alert-triangle" size={14} />
            <span className="truncate">{credential.last_error}</span>
          </p>
        )}
      </div>
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
    </Card>
  )
}
