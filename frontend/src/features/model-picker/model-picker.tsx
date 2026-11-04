import { Link } from '@tanstack/react-router'
import { useCallback } from 'react'
import {
  choiceLabel,
  getModelChoice,
  type LlmCredential,
  type ModelChoice,
  modelLabel,
  resolveChoice,
  SERVER_MODEL_LABEL,
  useLlmCredentials,
  useLlmModels,
  useModelChoiceStore,
} from '@/entities/llm-credential'
import { useCurrentUser } from '@/entities/session'
import {
  Button,
  Popover,
  PopoverContent,
  PopoverTrigger,
  Select,
  Skeleton,
  Tooltip,
} from '@/shared/ui'

/** Выбор модели для запуска: ключ и модель; запоминается для каждого пользователя на устройстве. */
export function ModelPicker() {
  const user = useCurrentUser()
  const credentials = useLlmCredentials(Boolean(user))
  const choices = useModelChoiceStore((state) => state.choices)
  const setChoice = useModelChoiceStore((state) => state.set)
  if (!user) return null
  const items = credentials.data?.items ?? []
  const stored = choices[user.id] ?? getModelChoice(user.id)
  const choice = stored && items.some((item) => item.id === stored.credentialId) ? stored : null
  const label = choiceLabel(items, choice)

  return (
    <Popover>
      <Tooltip content="Модель для запуска" side="bottom">
        <PopoverTrigger asChild>
          <Button
            variant="ghost"
            size="sm"
            leadingIcon="sparkles"
            trailingIcon="chevron-down"
            aria-label={`Модель: ${label}`}
            className="max-w-64 text-fg-muted [&>span]:truncate"
          >
            <span className="truncate">{label}</span>
          </Button>
        </PopoverTrigger>
      </Tooltip>
      <PopoverContent align="end" className="w-80" aria-label="Выбор модели">
        <PickerBody
          items={items}
          loading={credentials.isPending}
          choice={choice}
          onChange={(next) => setChoice(user.id, next)}
        />
      </PopoverContent>
    </Popover>
  )
}

export function PickerBody({
  items,
  loading,
  choice,
  onChange,
}: {
  items: LlmCredential[]
  loading: boolean
  choice: ModelChoice | null
  onChange: (choice: ModelChoice | null) => void
}) {
  const resolved = resolveChoice(items, choice)
  const models = useLlmModels(resolved?.credential.id)
  const changeKey = useCallback(
    (value: string) => {
      if (value === SERVER) return onChange(null)
      const credential = items.find((item) => item.id === value)
      if (credential?.default_model) {
        onChange({ credentialId: credential.id, model: credential.default_model })
      }
    },
    [items, onChange],
  )

  if (loading) return <Skeleton className="h-16 w-full" />
  const keyOptions = [
    { value: SERVER, label: SERVER_MODEL_LABEL, icon: 'settings' as const },
    ...items.map((item) => ({ value: item.id, label: item.label, icon: 'key' as const })),
  ]
  const ids = (models.data ?? []).map((item) => item.id)
  if (resolved && !ids.includes(resolved.model)) ids.unshift(resolved.model)

  return (
    <div className="flex flex-col gap-3">
      <Select
        aria-label="Ключ"
        options={keyOptions}
        value={choice ? choice.credentialId : (resolved?.credential.id ?? SERVER)}
        onValueChange={changeKey}
      />
      {resolved && (
        <Select
          aria-label="Модель"
          options={ids.map((id) => ({ value: id, label: modelLabel(id) }))}
          value={resolved.model}
          onValueChange={(model) => onChange({ credentialId: resolved.credential.id, model })}
        />
      )}
      <Link to="/settings" className="type-caption text-accent-fg hover:underline">
        Ключи и модели в настройках
      </Link>
    </div>
  )
}

const SERVER = '__server__'
