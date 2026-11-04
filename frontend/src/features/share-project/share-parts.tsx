import { type ReactNode, useState } from 'react'
import { emailInitialsName } from '@/entities/session'
import {
  expiryOptions,
  linkScopeText,
  type ProjectMember,
  SHARE_ROLE,
  SHARE_ROLES,
  type ShareLink,
  type ShareRole,
  shareTokenFromPath,
} from '@/entities/share'
import { AgentPromptDialog } from '@/features/share-reviewer/agent-prompt-dialog'
import { cn } from '@/shared/lib/cn'
import { formatDate } from '@/shared/lib/format'
import { TOUR_ANCHORS, tourAnchor } from '@/shared/lib/tour-anchors'
import {
  Avatar,
  Button,
  Card,
  Checkbox,
  ConfirmDialog,
  Field,
  IconButton,
  Input,
  RadioGroup,
  RadioGroupItem,
  ScrollArea,
  SegmentedControl,
  Select,
  Skeleton,
  Tag,
} from '@/shared/ui'
import { type ReviewScopeMode, ROLE_HINT, useCopy } from './model'

const date = (iso: string) => formatDate(new Date(iso))

export interface ShareCreateFormProps {
  role: ShareRole
  days: number
  /** Область проверки: весь проект или отмеченные дорожки (только для `reviewer`). */
  scope: ReviewScopeMode
  /** Названия дорожек последней схемы; пусто — схемы ещё нет. */
  lanes: readonly string[]
  selectedLanes: readonly string[]
  onRoleChange: (role: ShareRole) => void
  onDaysChange: (days: number) => void
  onScopeChange: (scope: ReviewScopeMode) => void
  onLanesChange: (lanes: string[]) => void
  onCreate: () => void
  pending?: boolean
  lanesLoading?: boolean
  lanesError?: boolean
}

/** Новая ссылка: роль, область проверки, срок и одна главная кнопка. */
export function ShareCreateForm({
  role,
  days,
  scope,
  lanes,
  selectedLanes,
  onRoleChange,
  onDaysChange,
  onScopeChange,
  onLanesChange,
  onCreate,
  pending,
  lanesLoading = false,
  lanesError = false,
}: ShareCreateFormProps) {
  const reviewer = role === 'reviewer'
  const selectedEmpty = reviewer && scope === 'selected' && selectedLanes.length === 0
  return (
    <form
      className="flex flex-col gap-4"
      onSubmit={(event) => {
        event.preventDefault()
        if (!selectedEmpty) onCreate()
      }}
    >
      <div {...tourAnchor(TOUR_ANCHORS.shareReviewer)}>
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
      </div>
      {reviewer && (
        <ScopeField
          scope={scope}
          lanes={lanes}
          selected={selectedLanes}
          loading={lanesLoading}
          error={lanesError}
          onScopeChange={onScopeChange}
          onSelectedChange={onLanesChange}
        />
      )}
      <div className="flex items-end gap-3">
        <Field label="Срок действия" className="flex-1">
          <Select
            options={expiryOptions(role)}
            value={String(days)}
            onValueChange={(value) => onDaysChange(Number(value))}
          />
        </Field>
        <Button
          type="submit"
          variant="primary"
          leadingIcon="link"
          loading={pending}
          disabled={selectedEmpty}
          {...tourAnchor(TOUR_ANCHORS.shareCreate)}
        >
          Создать ссылку
        </Button>
      </div>
    </form>
  )
}

/** Область проверки: весь проект (по умолчанию) или выбранные дорожки схемы. */
function ScopeField({
  scope,
  lanes,
  selected,
  loading,
  error,
  onScopeChange,
  onSelectedChange,
}: {
  scope: ReviewScopeMode
  lanes: readonly string[]
  selected: readonly string[]
  loading: boolean
  error: boolean
  onScopeChange: (scope: ReviewScopeMode) => void
  onSelectedChange: (lanes: string[]) => void
}) {
  const noLanes = !loading && lanes.length === 0
  const unavailable = !loading && (error || lanes.length === 0)
  return (
    <fieldset className="flex flex-col gap-2.5">
      <legend className="type-label mb-1 text-fg">Область проверки</legend>
      <RadioGroup
        orientation="horizontal"
        value={scope}
        onValueChange={(next) => onScopeChange(next as ReviewScopeMode)}
        aria-label="Область проверки"
      >
        <RadioGroupItem value="all" label="Весь проект" />
        <RadioGroupItem
          value="selected"
          label="Выбранные дорожки"
          disabled={unavailable}
          description={unavailable ? 'Список дорожек недоступен' : undefined}
        />
      </RadioGroup>
      {loading && <Skeleton className="h-12 w-full rounded-md" />}
      {noLanes && (
        <p className="type-caption text-fg-muted">
          {error
            ? 'Список дорожек не загрузился: ссылка откроет весь проект.'
            : 'Дорожек в схеме пока нет: ссылка откроет весь проект.'}
        </p>
      )}
      {scope === 'selected' && lanes.length > 0 && (
        <Card variant="sunken" padding="none">
          <ScrollArea className="max-h-44" viewportClassName="max-h-44">
            <div className="flex flex-col gap-2 p-3">
              {lanes.map((lane) => (
                <Checkbox
                  key={lane}
                  label={lane}
                  checked={selected.includes(lane)}
                  onCheckedChange={(checked) =>
                    onSelectedChange(
                      checked === true
                        ? [...selected, lane]
                        : selected.filter((item) => item !== lane),
                    )
                  }
                />
              ))}
            </div>
          </ScrollArea>
        </Card>
      )}
      {scope === 'selected' && lanes.length > 0 && selected.length === 0 && (
        <p role="alert" className="type-caption text-danger-fg">
          Отметьте хотя бы одну дорожку или выберите «Весь проект».
        </p>
      )}
      {scope === 'all' && (
        <p className="type-caption text-fg-muted">
          Коллега увидит все дорожки и общие вопросы проекта.
        </p>
      )}
    </fieldset>
  )
}

export interface ShareLinkResultProps {
  url: string
  access: ShareRole
  expiresAt: string | null
  /** Область проверки: ids или названия дорожек из ответа сервера. */
  laneIds?: string[]
  onAnother: () => void
}

/**
 * Только что созданная ссылка. Полный адрес сервер отдаёт один раз, поэтому показываем его
 * здесь с кнопкой копирования; в списке ссылок адреса уже не будет. У проверки сразу доступен
 * готовый запрос для агента — его можно скопировать до закрытия окна.
 */
export function ShareLinkResult({
  url,
  access,
  expiresAt,
  laneIds,
  onAnother,
}: ShareLinkResultProps) {
  const { copied, copy } = useCopy()
  const [promptOpen, setPromptOpen] = useState(false)
  const token = shareTokenFromPath(url)
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
              {...tourAnchor(TOUR_ANCHORS.shareCopy)}
              onClick={() => void copy(url)}
            />
          }
        />
      </Field>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex flex-wrap items-center gap-2 type-caption text-fg-muted">
          <Tag icon={SHARE_ROLE[access].icon}>{SHARE_ROLE[access].label}</Tag>
          {access === 'reviewer' && <span>{linkScopeText(laneIds)}</span>}
          {expiresAt && <span>до {date(expiresAt)}</span>}
        </div>
        <div className="flex items-center gap-2">
          {access === 'reviewer' && token && (
            <Button
              variant="secondary"
              size="sm"
              leadingIcon="copy"
              onClick={() => setPromptOpen(true)}
              {...tourAnchor(TOUR_ANCHORS.shareCopyPrompt)}
            >
              Скопировать запрос для агента
            </Button>
          )}
          <Button variant="ghost" size="sm" onClick={onAnother}>
            Создать другую
          </Button>
        </div>
      </div>
      {access === 'reviewer' && token && (
        <AgentPromptDialog token={token} open={promptOpen} onOpenChange={setPromptOpen} />
      )}
    </div>
  )
}

const REVOKE_TEXT: Record<ShareRole, string> = {
  viewer: 'По ней больше нельзя будет открыть проект.',
  editor: 'Приглашение перестанет действовать. Уже принявшие останутся в проекте.',
  reviewer: 'Проверка закроется: ссылка и выданный по ней токен агента перестанут работать.',
}

/** Строка действующей ссылки: роль, область, срок, дата создания, копирование и отзыв. */
export function ShareLinkRow({
  link,
  copyUrl,
  onRevoke,
}: {
  link: ShareLink
  /** Полный адрес, если ссылку создали в этом же открытом окне: сервер отдаёт его один раз. */
  copyUrl?: string
  onRevoke: () => void
}) {
  const { copied, copy } = useCopy()
  return (
    <Row
      leading={
        <div className="flex flex-col items-start gap-1">
          <Tag icon={SHARE_ROLE[link.role].icon}>{SHARE_ROLE[link.role].label}</Tag>
          {link.role === 'reviewer' && (
            <span className="type-caption text-fg-subtle">{linkScopeText(link.lane_ids)}</span>
          )}
        </div>
      }
      leadingClassName="w-40"
      title={link.expires_at ? `До ${date(link.expires_at)}` : 'Бессрочно'}
      meta={`Создана ${date(link.created_at)}`}
      action={
        <div className="flex items-center gap-0.5">
          {copyUrl && (
            <IconButton
              icon={copied ? 'check' : 'copy'}
              size="sm"
              label="Копировать ссылку"
              onClick={() => void copy(copyUrl)}
            />
          )}
          <ConfirmDialog
            trigger={<IconButton icon="trash" size="sm" tone="danger" label="Отозвать ссылку" />}
            title="Отозвать ссылку?"
            description={REVOKE_TEXT[link.role]}
            confirmLabel="Отозвать"
            tone="danger"
            onConfirm={onRevoke}
          />
        </div>
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
