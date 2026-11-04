import { Field, SecretInput } from '@/shared/ui'

/** Поле ключа: скрыто по умолчанию, глаз показывает; браузер и менеджер паролей его не запоминают. */
export function KeyField({
  value,
  onChange,
  error,
}: {
  value: string
  onChange: (value: string) => void
  error?: string
}) {
  return (
    <Field label="API-ключ" error={error}>
      <SecretInput
        name="api-key"
        value={value}
        placeholder="sk-…"
        revealLabel="Показать ключ"
        hideLabel="Скрыть ключ"
        onChange={(event) => onChange(event.target.value)}
      />
    </Field>
  )
}
