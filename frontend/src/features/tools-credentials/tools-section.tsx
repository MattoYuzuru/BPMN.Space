import { useRef, useState } from 'react'
import {
  availableProviders,
  type Credential,
  type CredentialProvider,
  useCheckToolCredential,
  useDeleteToolCredential,
  useToolCredentials,
  useUpdateToolCredential,
} from '@/entities/tool-credential'
import { TOUR_ANCHORS, tourAnchor } from '@/shared/lib/tour-anchors'
import { Badge, Button, Card, ConfirmDialog, EmptyState, Icon, Skeleton } from '@/shared/ui'
import { CapabilityCardView } from './capability-card'
import { CredentialDialog } from './credential-dialog'
import { CredentialRow } from './credential-row'

/**
 * Настройки, раздел «Инструменты» (RFC-0006, шаг 1): карточки возможностей, ключи по типам задач,
 * приоритеты, лимиты и проверка. Раздел «Модели и ключи» остаётся для совместимости.
 */
export function ToolsSection() {
  const credentials = useToolCredentials()
  const update = useUpdateToolCredential()
  const remove = useDeleteToolCredential()
  const check = useCheckToolCredential()
  const [adding, setAdding] = useState(false)
  const [editing, setEditing] = useState<Credential | null>(null)
  const [deleting, setDeleting] = useState<Credential | null>(null)
  const titleRef = useRef<HTMLHeadingElement>(null)
  const deletedRef = useRef(false)

  const storage = credentials.data?.storage_available ?? true
  const items = credentials.data?.items ?? []
  const capabilities = credentials.data?.capabilities ?? []
  const providers: CredentialProvider[] = availableProviders(capabilities)

  const openAdd = () => setAdding(true)

  return (
    <section
      aria-labelledby="tools-title"
      className="flex flex-col gap-4"
      {...tourAnchor(TOUR_ANCHORS.settingsTools)}
    >
      <div className="flex items-center gap-3">
        <h2
          id="tools-title"
          ref={titleRef}
          tabIndex={-1}
          className="type-heading flex-1 text-fg outline-none"
        >
          Инструменты
        </h2>
        <Button
          leadingIcon="plus"
          size="sm"
          variant="primary"
          disabled={!storage}
          onClick={openAdd}
          {...tourAnchor(TOUR_ANCHORS.toolsAddKey)}
        >
          Добавить ключ
        </Button>
      </div>
      <p className="type-ui text-fg-muted">
        Ключи по типам задач: распознавание речи, текст со сканов, изображения, поиск. Один ключ
        может закрывать несколько задач; приоритет решает, какой пробовать первым.
      </p>

      {credentials.isPending && <Skeleton className="h-16 w-full" />}
      {credentials.isError && (
        <p role="alert" className="type-ui text-danger-fg">
          Не удалось загрузить ключи инструментов.
        </p>
      )}
      {!storage && (
        <Card variant="sunken" padding="sm" className="flex items-center gap-2">
          <Icon name="alert-triangle" size={16} className="text-amber-fg" />
          <span className="type-ui text-fg-muted">
            Хранение ключей не настроено на сервере. Работают ключи и модели оператора.
          </span>
        </Card>
      )}

      {credentials.data && (
        <div className="flex flex-col gap-2">
          <span className="type-label text-fg-muted">Возможности</span>
          {capabilities.length === 0 && (
            <p className="type-caption text-fg-subtle">Сервер не сообщил возможности.</p>
          )}
          <ul className="flex flex-col gap-2">
            {capabilities.map((card) => (
              <li key={card.capability}>
                <CapabilityCardView card={card} onAdd={openAdd} />
              </li>
            ))}
          </ul>
        </div>
      )}

      <div className="flex flex-col gap-2">
        <div className="flex items-center gap-2">
          <span className="type-label text-fg-muted">Ключи</span>
          {items.length > 0 && (
            <Badge tone="neutral" variant="outline">
              {items.length}
            </Badge>
          )}
        </div>
        {credentials.data && items.length === 0 && storage && (
          <Card variant="sunken" padding="none">
            <EmptyState
              icon="key"
              size="sm"
              backdrop="none"
              title="Ключей инструментов нет"
              description="Пока используются ключ модели и серверные провайдеры."
            />
          </Card>
        )}
        <ul className="flex flex-col gap-2">
          {items.map((credential) => (
            <li key={credential.id}>
              <CredentialRow
                credential={credential}
                providers={providers}
                checking={check.isPending && check.variables === credential.id}
                onCheck={() => check.mutate(credential.id)}
                onEdit={() => setEditing(credential)}
                onToggle={(enabled) =>
                  update.mutate({ id: credential.id, enabled, clear_monthly_limit: false })
                }
                onDelete={() => setDeleting(credential)}
              />
            </li>
          ))}
        </ul>
      </div>

      <CredentialDialog
        key={`new-${adding ? 'open' : 'closed'}`}
        open={adding}
        credential={null}
        capabilities={capabilities}
        onOpenChange={(open) => {
          if (!open) setAdding(false)
        }}
      />
      {editing && (
        <CredentialDialog
          key={editing.id}
          open
          credential={editing}
          capabilities={capabilities}
          onOpenChange={(open) => {
            if (!open) setEditing(null)
          }}
        />
      )}
      <ConfirmDialog
        open={deleting !== null}
        onOpenChange={(open) => {
          if (open) return
          setDeleting(null)
          if (deletedRef.current) {
            deletedRef.current = false
            window.setTimeout(() => titleRef.current?.focus(), 100)
          }
        }}
        title={`Удалить ключ «${deleting?.label ?? ''}»?`}
        description="Ключ стирается с сервера. Прогоны, которые идут с ним сейчас, завершатся с техническим вопросом."
        confirmLabel="Удалить"
        tone="danger"
        onConfirm={async () => {
          if (!deleting) return
          await remove.mutateAsync(deleting.id)
          deletedRef.current = true
        }}
      />
    </section>
  )
}
