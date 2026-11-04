import { useEffect } from 'react'
import { type LlmCredential, modelLabel, useLlmModels } from '@/entities/llm-credential'
import { Field, Select, Skeleton } from '@/shared/ui'

/** Выбор модели из списка, который вернул провайдер; текущая модель остаётся, даже если её нет в списке. */
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
  useEffect(() => {
    if (!value && first) onChange(first)
  }, [value, first, onChange])

  if (models.isPending) return <Skeleton className="h-8 w-full" />
  return (
    <Field
      label={label}
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
