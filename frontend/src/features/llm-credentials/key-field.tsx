import { useState } from 'react'
import { Field, IconButton, Input } from '@/shared/ui'

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
  const [visible, setVisible] = useState(false)
  return (
    <Field label="API-ключ" error={error}>
      <Input
        name="api-key"
        type={visible ? 'text' : 'password'}
        autoComplete="off"
        autoCapitalize="none"
        spellCheck={false}
        leadingIcon="key"
        value={value}
        placeholder="sk-…"
        onChange={(event) => onChange(event.target.value)}
        trailing={
          <IconButton
            icon={visible ? 'eye-off' : 'eye'}
            size="sm"
            label={visible ? 'Скрыть ключ' : 'Показать ключ'}
            tooltip={false}
            aria-pressed={visible}
            onClick={() => setVisible((current) => !current)}
          />
        }
      />
    </Field>
  )
}
