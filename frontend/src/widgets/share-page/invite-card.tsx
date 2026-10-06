import { Link } from '@tanstack/react-router'
import { BrandMark, Button, Card, Icon, Skeleton, Tag } from '@/shared/ui'

export type InviteCardState =
  /** Гость: сначала войти. */
  | { kind: 'sign-in'; token: string }
  /** Вошедший: принять приглашение. */
  | { kind: 'accept'; title: string; pending: boolean; onAccept: () => void }
  /** У вошедшего доступ уже есть: открыть проект. */
  | { kind: 'member'; title: string; projectId: string }
  /** Проверяем, есть ли доступ. */
  | { kind: 'checking'; title: string }

/**
 * Приглашение редактировать проект. Тот же язык, что у экрана входа: знак, заголовок и узкая
 * карточка. Карточка одна и даёт одно действие — войти, принять или открыть.
 */
export function InviteCard({ state }: { state: InviteCardState }) {
  return (
    <div className="flex w-full max-w-sm flex-col items-center gap-6">
      <div className="flex flex-col items-center gap-4 text-center">
        <BrandMark size="lg" />
        <h1 className="type-title text-fg">Приглашение в проект</h1>
      </div>
      <Card variant="elevated" padding="lg" className="flex w-full flex-col gap-5" data-lens-block>
        {state.kind !== 'sign-in' && (
          <div className="flex items-center gap-3">
            <span className="grid size-10 shrink-0 place-items-center rounded-md border border-border bg-bg-subtle text-fg-muted">
              <Icon name="folder" size={20} />
            </span>
            <div className="flex min-w-0 flex-col items-start gap-1">
              <span className="w-full truncate type-heading text-fg">{state.title}</span>
              <Tag icon="pencil">Редактирование</Tag>
            </div>
          </div>
        )}
        {state.kind === 'sign-in' && (
          <p className="type-body text-fg-muted">
            Чтобы принять приглашение и редактировать проект, войдите в аккаунт или создайте его.
          </p>
        )}
        {state.kind === 'sign-in' && (
          <Button asChild variant="primary" size="lg" className="w-full">
            <Link to="/login" search={{ redirect: `/share/${state.token}` }}>
              Войти, чтобы принять
            </Link>
          </Button>
        )}
        {state.kind === 'accept' && (
          <Button
            variant="primary"
            size="lg"
            className="w-full"
            loading={state.pending}
            onClick={state.onAccept}
          >
            Принять приглашение
          </Button>
        )}
        {state.kind === 'member' && (
          <Button asChild variant="primary" size="lg" className="w-full">
            <Link to="/projects/$projectId" params={{ projectId: state.projectId }}>
              Открыть проект
            </Link>
          </Button>
        )}
        {state.kind === 'checking' && <Skeleton className="h-10 rounded-md" />}
      </Card>
    </div>
  )
}
