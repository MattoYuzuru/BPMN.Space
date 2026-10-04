import type { ReactNode } from 'react'
import { emailInitialsName } from '@/entities/session'
import {
  expiryOptions,
  type ProjectMember,
  SHARE_ROLE,
  SHARE_ROLES,
  type ShareLink,
  type ShareRole,
} from '@/entities/share'
import { cn } from '@/shared/lib/cn'
import { formatDate } from '@/shared/lib/format'
import {
  Avatar,
  Button,
  ConfirmDialog,
  Field,
  IconButton,
  Input,
  SegmentedControl,
  Select,
  Tag,
} from '@/shared/ui'
import { ROLE_HINT, useCopy } from './model'

const date = (iso: string) => formatDate(new Date(iso))

export interface ShareCreateFormProps {
  role: ShareRole
  days: number
  onRoleChange: (role: ShareRole) => void
  onDaysChange: (days: number) => void
  onCreate: () => void
  pending?: boolean
}

/** Новая ссылка: роль, срок и одна главная кнопка. Сроки зависят от роли. */
export function ShareCreateForm({
  role,
  days,
  onRoleChange,
  onDaysChange,
  onCreate,
  pending,
}: ShareCreateFormProps) {
  return (
    <form
      className="flex flex-col gap-4"
      onSubmit={(event) => {
        event.preventDefault()
        onCreate()
      }}
    >
      <Field label="Доступ" hint={ROLE_HINT[role]}>
        <SegmentedControl
          aria-label="Доступ"
          options={SHARE_ROLES.map((value) => ({
            value,
            label: SHARE_ROLE[value].label,
            icon: SHARE_ROLE[value].icon,
          }))}
          value={role}
          onValueChange={onRoleChange}
        />
      </Field>
      <div className="flex items-end gap-3">
        <Field label="Срок действия" className="flex-1">
          <Select
            options={expiryOptions(role)}
            value={String(days)}
            onValueChange={(value) => onDaysChange(Number(value))}
          />
        </Field>
        <Button type="submit" variant="primary" leadingIcon="link" loading={pending}>
          Создать ссылку
        </Button>
      </div>
    </form>
  )
}

export interface ShareLinkResultProps {
  url: string
  access: ShareRole
  expiresAt: string | null
  onAnother: () => void
}

/**
 * Только что созданная ссылка. Полный адрес сервер отдаёт один раз, поэтому показываем его
 * здесь с кнопкой копирования; в списке ссылок адреса уже не будет.
 */
export function ShareLinkResult({ url, access, expiresAt, onAnother }: ShareLinkResultProps) {
  const { copied, copy } = useCopy()
  return (
    <div className="flex flex-col gap-3">
      <Field label="Ссылка" hint="Адрес показывается один раз.">
        <Input
          readOnly
          value={url}
          leadingIcon="link"
          onFocus={(event) => event.currentTarget.select()}
          trailing={
            <IconButton
              icon={copied ? 'check' : 'copy'}
              size="sm"
              label="Копировать ссылку"
              onClick={() => void copy(url)}
            />
          }
        />
      </Field>
      <div className="flex items-center justify-between gap-3">
        <div className="flex items-center gap-2 type-caption text-fg-muted">
          <Tag icon={SHARE_ROLE[access].icon}>{SHARE_ROLE[access].label}</Tag>
          {expiresAt && <span>до {date(expiresAt)}</span>}
        </div>
        <Button variant="ghost" size="sm" onClick={onAnother}>
          Создать другую
        </Button>
      </div>
    </div>
  )
}

const REVOKE_TEXT: Record<ShareRole, string> = {
  viewer: 'По ней больше нельзя будет открыть проект.',
  editor: 'Приглашение перестанет действовать. Уже принявшие останутся в проекте.',
}

/** Строка действующей ссылки: роль, срок, дата создания и отзыв с подтверждением. */
export function ShareLinkRow({ link, onRevoke }: { link: ShareLink; onRevoke: () => void }) {
  return (
    <Row
      leading={<Tag icon={SHARE_ROLE[link.role].icon}>{SHARE_ROLE[link.role].label}</Tag>}
      leadingClassName="w-36"
      title={link.expires_at ? `До ${date(link.expires_at)}` : 'Бессрочно'}
      meta={`Создана ${date(link.created_at)}`}
      action={
        <ConfirmDialog
          trigger={<IconButton icon="trash" size="sm" tone="danger" label="Отозвать ссылку" />}
          title="Отозвать ссылку?"
          description={REVOKE_TEXT[link.role]}
          confirmLabel="Отозвать"
          tone="danger"
          onConfirm={onRevoke}
        />
      }
    />
  )
}

/** Строка участника: почта, уровень доступа и удаление с подтверждением. */
export function MemberRow({ member, onRemove }: { member: ProjectMember; onRemove: () => void }) {
  return (
    <Row
      leading={<Avatar name={emailInitialsName(member.email)} size="lg" />}
      title={member.email}
      meta={`С ${date(member.added_at)}`}
      trailing={
        <Tag icon={SHARE_ROLE[member.role].icon}>
          {member.role === 'editor' ? 'Редактор' : 'Наблюдатель'}
        </Tag>
      }
      action={
        <ConfirmDialog
          trigger={<IconButton icon="trash" size="sm" tone="danger" label="Убрать участника" />}
          title="Убрать участника?"
          description={`${member.email} потеряет доступ к проекту.`}
          confirmLabel="Убрать"
          tone="danger"
          onConfirm={onRemove}
        />
      }
    />
  )
}

function Row({
  leading,
  leadingClassName,
  title,
  meta,
  trailing,
  action,
}: {
  leading: ReactNode
  leadingClassName?: string
  title: string
  meta: string
  trailing?: ReactNode
  action: ReactNode
}) {
  return (
    <li className="flex items-center gap-3 py-2.5">
      <div className={cn('flex shrink-0 items-center', leadingClassName)}>{leading}</div>
      <div className="flex min-w-0 flex-1 flex-col">
        <span className="truncate type-ui text-fg">{title}</span>
        <span className="type-caption text-fg-subtle">{meta}</span>
      </div>
      {trailing}
      {action}
    </li>
  )
}
