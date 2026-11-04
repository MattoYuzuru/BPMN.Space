import { useState } from 'react'
import type { SharedProject } from '@/entities/share'
import { TOUR_ANCHORS, tourAnchor } from '@/shared/lib/tour-anchors'
import { Badge, Button } from '@/shared/ui'
import { AgentConnectDialog } from './agent-connect-dialog'
import { AgentPromptDialog } from './agent-prompt-dialog'
import { ReviewAnswers } from './review-answers'

/** Область проверки словами: весь проект или названия дорожек из ответа сервера. */
export function reviewScopeText(scope: SharedProject['scope']): string {
  if (scope.whole_project) return 'Весь проект'
  return scope.lanes?.length ? scope.lanes.join(', ') : 'Выбранные дорожки'
}

/**
 * Полоса проверки на публичной странице: что открыто коллеге, что схема только для чтения.
 * Ответить на вопросы области можно без входа — форма ниже; подключение агента нужно для
 * автоматических ответов, поэтому рядом остаются запрос и токен для агента.
 */
export function ReviewInvite({ token, shared }: { token: string; shared: SharedProject }) {
  const [promptOpen, setPromptOpen] = useState(false)
  const [connectOpen, setConnectOpen] = useState(false)
  const scope = reviewScopeText(shared.scope)

  return (
    <>
      <section
        aria-label="Проверка коллегой"
        className="flex shrink-0 flex-wrap items-center gap-x-3 gap-y-2 border-b border-border bg-surface px-4 py-2.5 wide:px-5"
        {...tourAnchor(TOUR_ANCHORS.reviewPanel)}
      >
        <Badge tone="accent" variant="outline" icon="users">
          Проверка
        </Badge>
        <p className="min-w-0 flex-1 type-ui text-fg-muted">
          <span className="text-fg">{scope}.</span> Схема открыта только для чтения. На вопросы
          области можно ответить без входа — форма ниже; подключение агента — для автоматических
          ответов.
        </p>
        <Button
          size="sm"
          variant="secondary"
          leadingIcon="copy"
          onClick={() => setPromptOpen(true)}
          {...tourAnchor(TOUR_ANCHORS.shareCopyPrompt)}
        >
          Запрос для агента
        </Button>
        <Button size="sm" variant="primary" leadingIcon="key" onClick={() => setConnectOpen(true)}>
          Подключить агента
        </Button>
        <AgentPromptDialog token={token} open={promptOpen} onOpenChange={setPromptOpen} />
        <AgentConnectDialog
          token={token}
          open={connectOpen}
          onOpenChange={setConnectOpen}
          shareRole={shared.role}
          scopeText={scope}
        />
      </section>
      <ReviewAnswers token={token} />
    </>
  )
}
