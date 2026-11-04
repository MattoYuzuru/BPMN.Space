import { Link } from '@tanstack/react-router'
import { useCallback, useId } from 'react'
import {
  choiceLabel,
  effectiveEffort,
  effortOptions,
  getModelChoice,
  isEffort,
  type LlmCredential,
  type LlmModel,
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
  RadioGroup,
  RadioGroupItem,
  Select,
  Skeleton,
  Tooltip,
} from '@/shared/ui'

/**
 * Выбор модели для запуска: ключ, модель и глубина работы (RFC-0005); запоминается для каждого
 * пользователя на устройстве и уходит в профиль анализа и сборки.
 */
export function ModelPicker() {
  const user = useCurrentUser()
  const credentials = useLlmCredentials(Boolean(user))
  const choices = useModelChoiceStore((state) => state.choices)
  const setChoice = useModelChoiceStore((state) => state.set)
  const items = credentials.data?.items ?? []
  const stored = user ? (choices[user.id] ?? getModelChoice(user.id)) : null
  const choice = stored && items.some((item) => item.id === stored.credentialId) ? stored : null
  const resolved = resolveChoice(items, choice)
  // Список моделей кэшируется и на сервере, и здесь: уровень в метке без лишних запросов.
  const models = useLlmModels(resolved?.credential.id, { background: true })
  if (!user) return null
  const label = choiceLabel(items, choice, capabilitiesOf(models.data, resolved?.model))

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
  demoModels,
}: {
  items: LlmCredential[]
  loading: boolean
  choice: ModelChoice | null
  onChange: (choice: ModelChoice | null) => void
  /** Готовый список моделей для витрины: живые запросы к API тогда не нужны. */
  demoModels?: LlmModel[]
}) {
  const resolved = resolveChoice(items, choice)
  // В образцах стилгайда модели передаются готовыми — запрос к ключу не уходит.
  const models = useLlmModels(demoModels ? undefined : resolved?.credential.id)
  const modelList = demoModels ?? models.data
  const effortId = useId()
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
  const ids = (modelList ?? []).map((item) => item.id)
  if (resolved && !ids.includes(resolved.model)) ids.unshift(resolved.model)
  const caps = capabilitiesOf(modelList, resolved?.model)
  const levels = effortOptions(caps)
  const effort = effectiveEffort(resolved?.effort, caps)
  const changeModel = (model: string) => {
    if (!resolved) return
    // Уровень переносится, только если новая модель его поддерживает.
    const next = capabilitiesOf(modelList, model)
    const keep = resolved.effort && next?.effort_levels.includes(resolved.effort)
    onChange({
      credentialId: resolved.credential.id,
      model,
      ...(keep ? { effort: resolved.effort } : {}),
    })
  }

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
          onValueChange={changeModel}
        />
      )}
      {resolved && effort && levels.length > 1 && (
        <div className="flex flex-col gap-2">
          <span id={effortId} className="type-caption text-fg-muted">
            Глубина работы
          </span>
          <RadioGroup
            aria-labelledby={effortId}
            value={effort}
            onValueChange={(value) => {
              if (!isEffort(value)) return
              onChange({
                credentialId: resolved.credential.id,
                model: resolved.model,
                effort: value,
              })
            }}
          >
            {levels.map((item) => (
              <RadioGroupItem key={item.value} value={item.value} label={item.label} />
            ))}
          </RadioGroup>
        </div>
      )}
      <Link to="/settings" className="type-caption text-accent-fg hover:underline">
        Ключи и модели в настройках
      </Link>
    </div>
  )
}

const SERVER = '__server__'

function capabilitiesOf(models: LlmModel[] | undefined, model: string | undefined) {
  return model ? models?.find((item) => item.id === model)?.capabilities : undefined
}
