import { useEffect } from 'react'
import {
  capabilitySummary,
  LABEL_SEPARATOR,
  type LlmCredential,
  modelLabel,
  useLlmModels,
} from '@/entities/llm-credential'
import { Field, Select, Skeleton } from '@/shared/ui'

/**
 * Выбор модели из списка, который вернул провайдер; текущая модель остаётся, даже если её нет
 * в списке. Под полем — краткие возможности выбранной модели (окно, ответ, уровни, цены с датой).
 */
export function ModelSelect({
  credential,
  value,
  onChange,
  label = 'Модель по умолчанию',
}: {
  credential: LlmCredential
  value: string | null
  onChange: (model: string) => void
  label?: string
}) {
  const models = useLlmModels(credential.id)
  const ids = (models.data ?? []).map((item) => item.id)
  const options = (value && !ids.includes(value) ? [value, ...ids] : ids).map((id) => ({
    value: id,
    label: modelLabel(id),
  }))
  const first = options[0]?.value
  const caps = models.data?.find((item) => item.id === value)?.capabilities
  const summary = caps ? capabilitySummary(caps).join(LABEL_SEPARATOR) : ''
  useEffect(() => {
    if (!value && first) onChange(first)
  }, [value, first, onChange])

  if (models.isPending) {
    return (
      <div role="status" aria-busy="true" aria-label="Загружаю список моделей">
        <Skeleton className="h-8 w-full" />
      </div>
    )
  }
  return (
    <Field
      label={label}
      hint={summary ? capitalize(summary) : undefined}
      error={models.isError ? 'Не удалось получить список моделей. Проверьте ключ.' : undefined}
    >
      <Select
        options={options}
        value={value ?? undefined}
        onValueChange={onChange}
        placeholder="Выберите модель"
      />
    </Field>
  )
}

function capitalize(text: string): string {
  return text.charAt(0).toUpperCase() + text.slice(1)
}
