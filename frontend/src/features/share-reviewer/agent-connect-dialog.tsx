import { Link } from '@tanstack/react-router'
import { useState } from 'react'
import { type ApiScope, scopeLabel } from '@/entities/api-token'
import { useSession } from '@/entities/session'
import { type AgentTokenIssued, type ShareRole, useIssueAgentToken } from '@/entities/share'
import { AgentSetup } from '@/features/api-tokens/agent-setup'
import { ApiError, errorMessage } from '@/shared/api/client'
import { formatDate } from '@/shared/lib/format'
import { emitOnboardingSignal } from '@/shared/lib/onboarding-signals'
import { Badge, Button, CopyField, Dialog, DialogContent, EmptyState, Tag } from '@/shared/ui'

/** Текст ошибки выпуска токена: у каждой причины — своё объяснение. */
export function agentConnectFailure(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.status === 401) return 'Войдите в аккаунт, чтобы получить токен агента.'
    if (error.status === 403) return 'Токен агента выдаётся только по ссылке проверки.'
    if (error.status === 404 || error.status === 410) {
      return 'Ссылка недействительна или её срок истёк.'
    }
  }
  return errorMessage(error)
}

/** Права токена по-русски; незнакомое право показываем как есть, а не прячем. */
function scopesText(scopes: string[] | undefined): string {
  if (!scopes?.length) return 'Чтение проекта и ответы на вопросы'
  return scopes.map((scope) => scopeLabel(scope as ApiScope)).join(', ')
}

/**
 * «Подключить своего агента» по ссылке проверки: вошедший получает токен агента один раз,
 * адрес MCP-сервера и готовую команду `claude mcp add`. Гость сначала входит; по ссылке
 * просмотра токен не выдаётся — сервер отвечает 403.
 */
export function AgentConnectDialog({
  token,
  open,
  onOpenChange,
  shareRole,
  scopeText,
}: {
  token: string
  open: boolean
  onOpenChange: (open: boolean) => void
  shareRole: ShareRole
  /** Область проверки словами: «Весь проект» или названия дорожек. */
  scopeText: string
}) {
  const session = useSession()
  const signedIn = Boolean(session.data?.user)
  const authEnabled = session.data?.auth_enabled === true
  const issue = useIssueAgentToken(token)
  const [issued, setIssued] = useState<AgentTokenIssued | null>(null)

  const close = (next: boolean) => {
    // Пока сервер выпускает токен, окно не закрывается: иначе секрет, показываемый один раз,
    // потеряется. Закрытие после выпуска забывает секрет.
    if (!next && issue.isPending) return
    if (!next) {
      setIssued(null)
      issue.reset()
    }
    onOpenChange(next)
  }

  const reviewer = shareRole === 'reviewer'
  const footer = issued ? (
    <Button onClick={() => close(false)}>Готово</Button>
  ) : (
    <>
      <Button variant="ghost" disabled={issue.isPending} onClick={() => close(false)}>
        Отмена
      </Button>
      {reviewer && signedIn && (
        <Button
          variant="primary"
          leadingIcon="key"
          loading={issue.isPending}
          onClick={() => issue.mutate(undefined, { onSuccess: setIssued })}
        >
          Подключить агента
        </Button>
      )}
    </>
  )

  return (
    <Dialog open={open} onOpenChange={close}>
      <DialogContent
        size="lg"
        hideClose={issue.isPending}
        title={issued ? 'Агент подключён' : 'Подключить агента'}
        description={
          issued
            ? 'Скопируйте токен и настройку сейчас: секрет показывается один раз.'
            : 'Агент получит доступ к проекту проверки на срок ссылки и только в её области.'
        }
        footer={footer}
      >
        {!reviewer && (
          <EmptyState
            size="sm"
            backdrop="none"
            icon="lock"
            title="Токен агента выдаётся по ссылке проверки"
            description="Эта ссылка открывает проект только для чтения — подключить агента по ней нельзя."
          />
        )}
        {reviewer && issued && <IssuedAgent token={issued} scopeText={scopeText} />}
        {reviewer && !issued && !signedIn && <GuestIntro token={token} authEnabled={authEnabled} />}
        {reviewer && !issued && signedIn && (
          <div className="flex flex-col gap-3">
            <p className="type-ui text-fg">
              Агент прочитает схему и вопросы выбранных дорожек и сможет оставить ответы от вашего
              имени. Проект и его источники агент не изменит.
            </p>
            <div className="flex flex-wrap items-center gap-2">
              <Tag icon="route">{scopeText}</Tag>
              <Tag icon="key">Чтение проекта и ответы</Tag>
              <Tag icon="clock">На срок ссылки</Tag>
            </div>
            {issue.isError && (
              <p role="alert" className="type-ui text-danger-fg">
                {agentConnectFailure(issue.error)}
              </p>
            )}
          </div>
        )}
      </DialogContent>
    </Dialog>
  )
}

/** Гость: предложение войти, а на стенде без аккаунтов — честное объяснение. */
function GuestIntro({ token, authEnabled }: { token: string; authEnabled: boolean }) {
  return (
    <div className="flex flex-col gap-3">
      <p className="type-ui text-fg">
        {authEnabled
          ? 'Токен агента выдаётся вошедшему получателю ссылки. Войдите — и вернитесь на эту страницу.'
          : 'На этом стенде вход отключён, поэтому токен агента выпустить нельзя. Запрос для агента можно скопировать без входа.'}
      </p>
      {authEnabled && (
        <Button asChild variant="primary" leadingIcon="arrow-right" className="w-fit">
          <Link to="/login" search={{ redirect: `/share/${token}` }}>
            Войти, чтобы подключить
          </Link>
        </Button>
      )}
    </div>
  )
}

/** Секрет, адрес и команда подключения — единственный показ. */
function IssuedAgent({ token, scopeText }: { token: AgentTokenIssued; scopeText: string }) {
  return (
    <div className="flex flex-col gap-4">
      <CopyField
        label="Токен агента"
        value={token.secret}
        secret
        copyMessage="Токен скопирован"
        copyLabel="Копировать токен"
        leadingIcon="key"
        hint="Показывается один раз. Храните его как пароль и не пересылайте ссылку целиком."
      />
      <AgentSetup
        origin={new URL(token.mcp_url).origin}
        mcpUrl={token.mcp_url}
        secret={token.secret}
        onCopied={() => emitOnboardingSignal({ type: 'agent.command.copied' })}
      />
      <div className="flex flex-wrap items-center gap-2">
        <Badge tone="accent" variant="outline" icon="users">
          Проверка
        </Badge>
        <Tag icon="route">{scopeText}</Tag>
        <Tag icon="clock">До {formatDate(new Date(token.expires_at))}</Tag>
        <span className="type-caption text-fg-muted">{scopesText(token.scopes)}</span>
      </div>
      <p className="type-caption text-fg-muted">
        Отзыв или истечение ссылки закрывают токен сразу: он действует только вместе с ней.
      </p>
    </div>
  )
}
