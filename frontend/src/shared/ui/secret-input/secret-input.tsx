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
 * Поле секрета: ключ API и токен. Скрыто по умолчанию, глаз показывает; браузер и менеджер
 * паролей значение не запоминают. Секрет не попадает в DOM в открытом виде, пока его не покажут.
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
      autoComplete="off"
      autoCapitalize="none"
      spellCheck={false}
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
