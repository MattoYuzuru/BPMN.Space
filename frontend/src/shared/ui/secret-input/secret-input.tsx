import { useState } from 'react'
import { IconButton } from '../icon-button/icon-button'
import { Input, type InputProps } from '../input/input'

export interface SecretInputProps extends Omit<InputProps, 'type' | 'trailing'> {
  /** Подпись кнопки «показать» для скринридера. */
  revealLabel?: string
  /** Подпись кнопки «скрыть» для скринридера. */
  hideLabel?: string
  /** Показать значение сразу (по умолчанию скрыто). */
  initiallyVisible?: boolean
}

/**
 * Поле секрета: ключ API и токен. Скрыто по умолчанию, глаз показывает. Браузеру и менеджерам
 * паролей подсказываем не запоминать значение (`autocomplete="new-password"`, `data-1p-ignore`,
 * `data-lpignore`), но стопроцентной гарантии у веб-страницы нет — ключ не попадает в DOM
 * открытым текстом, пока его не покажут, и не уходит в заголовок вкладки или логи.
 */
export function SecretInput({
  revealLabel = 'Показать секрет',
  hideLabel = 'Скрыть секрет',
  initiallyVisible = false,
  leadingIcon = 'key',
  ...props
}: SecretInputProps) {
  const [visible, setVisible] = useState(initiallyVisible)
  return (
    <Input
      {...props}
      type={visible ? 'text' : 'password'}
      autoComplete="new-password"
      autoCapitalize="none"
      spellCheck={false}
      data-1p-ignore
      data-lpignore="true"
      leadingIcon={leadingIcon}
      trailing={
        <IconButton
          icon={visible ? 'eye-off' : 'eye'}
          size="sm"
          label={visible ? hideLabel : revealLabel}
          tooltip={false}
          aria-pressed={visible}
          onClick={() => setVisible((current) => !current)}
        />
      }
    />
  )
}
