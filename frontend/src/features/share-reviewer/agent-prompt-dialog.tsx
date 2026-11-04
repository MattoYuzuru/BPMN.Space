import { useQuery } from '@tanstack/react-query'
import { type AgentPrompt, agentPromptQueryOptions } from '@/entities/share'
import { ApiError, errorMessage } from '@/shared/api/client'
import {
  Badge,
  Button,
  CopyField,
  Dialog,
  DialogContent,
  EmptyState,
  Skeleton,
  Tag,
} from '@/shared/ui'

/** Текст ошибки загрузки промпта: у каждой причины — своё объяснение, а не «ошибка сервера». */
export function agentPromptFailure(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.status === 401) return 'Войдите в аккаунт: эта ссылка открывается после входа.'
    if (error.status === 403) return 'Ссылка не даёт доступ к запросу для агента.'
    if (error.status === 404 || error.status === 410) {
      return 'Ссылка недействительна или её срок истёк.'
    }
  }
  return errorMessage(error)
}

/** Область промпта словами: сервер сам говорит, весь проект или выбранные дорожки. */
export function agentPromptScope(prompt: AgentPrompt): string {
  if (prompt.whole_project) return 'Весь проект'
  return prompt.lanes?.length ? prompt.lanes.join(', ') : 'Выбранные дорожки'
}

/**
 * Готовый запрос «проверь дорожку» для агента коллеги. Текст приходит с сервера без секрета
 * ссылки, поэтому его можно вставить в любого агента; поле только для чтения с копированием.
 */
export function AgentPromptDialog({
  token,
  open,
  onOpenChange,
}: {
  token: string
  open: boolean
  onOpenChange: (open: boolean) => void
}) {
  const prompt = useQuery({ ...agentPromptQueryOptions(token), enabled: open })

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        size="lg"
        title="Запрос для агента"
        description="Вставьте этот текст своему агенту: он прочитает схему и проверит дорожки проекта."
        footer={<Button onClick={() => onOpenChange(false)}>Готово</Button>}
      >
        {prompt.isPending && (
          <div className="flex flex-col gap-3" aria-busy="true">
            <Skeleton className="h-5 w-40 rounded-sm" />
            <Skeleton className="h-28 w-full rounded-md" />
          </div>
        )}
        {prompt.isError && (
          <EmptyState
            size="sm"
            backdrop="none"
            icon="alert-circle"
            title="Запрос не загрузился"
            description={agentPromptFailure(prompt.error)}
            action={<Button onClick={() => void prompt.refetch()}>Повторить</Button>}
          />
        )}
        {prompt.data && <PromptBody prompt={prompt.data} />}
      </DialogContent>
    </Dialog>
  )
}

function PromptBody({ prompt }: { prompt: AgentPrompt }) {
  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center gap-2">
        <Badge tone="accent" variant="outline" icon="users">
          Проверка
        </Badge>
        <Tag icon="route">{agentPromptScope(prompt)}</Tag>
        {prompt.questions_recap && prompt.questions_recap.length > 0 && (
          <span className="type-caption text-fg-muted">
            Вопросов в области: {prompt.questions_recap.length}
          </span>
        )}
      </div>
      <CopyField
        label="Текст запроса"
        value={prompt.text}
        multiline
        minRows={8}
        maxRows={14}
        copyMessage="Запрос скопирован"
        copyLabel="Копировать запрос"
        hint="Секрета ссылки в тексте нет: его можно вставить в любого агента."
      />
      <div className="flex flex-col gap-1">
        <span className="type-label text-fg">Как это работает</span>
        <p className="type-ui text-fg-muted">
          Агент прочитает схему и вопросы выбранных дорожек, проверит их и оставит ответы в проекте.
          Токен для подключения выдаётся отдельно — кнопкой «Подключить агента».
        </p>
      </div>
    </div>
  )
}
