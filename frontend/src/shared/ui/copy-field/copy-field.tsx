import { type ReactNode, useState } from 'react'
import { useCopy } from '@/shared/hooks/use-copy'
import { cn } from '@/shared/lib/cn'
import { Field } from '../field/field'
import type { IconName } from '../icon'
import { IconButton } from '../icon-button/icon-button'
import { Input } from '../input/input'
import { Textarea } from '../textarea/textarea'

export interface CopyFieldBaseProps {
  /** Значение: адрес, токен, команда подключения. Копируется целиком. */
  value: string
  /** Подпись поля. */
  label: ReactNode
  /** Тост после успешного копирования. */
  copyMessage?: string
  /** Подпись кнопки копирования для скринридера. */
  copyLabel?: string
  hint?: ReactNode
  minRows?: number
  maxRows?: number
  /** Иконка слева внутри поля. */
  leadingIcon?: IconName
  /** Успешно скопировали: клиентский сигнал обучения, аналитика. */
  onCopied?: () => void
  className?: string
}

/**
 * Многострочный секрет не поддерживаем: `textarea` не умеет `type="password"` и показала бы
 * значение без маски. Сочетание запрещено типами.
 */
export type CopyFieldProps = CopyFieldBaseProps &
  ({ secret: true; multiline?: false } | { secret?: false; multiline?: boolean })

/**
 * Поле только для чтения с копированием: одноразовый секрет, команда подключения, ссылка.
 * Секрет показывается по кнопке; буфер получает полное значение, а не маску.
 */
export function CopyField({
  value,
  label,
  copyMessage = 'Скопировано',
  copyLabel = typeof label === 'string' ? `Копировать: ${label.toLowerCase()}` : 'Копировать',
  hint,
  multiline = false,
  minRows = 2,
  maxRows = 4,
  secret = false,
  leadingIcon,
  onCopied,
  className,
}: CopyFieldProps) {
  const copy = useCopy(copyMessage)
  const [visible, setVisible] = useState(!secret)
  const copyValue = async () => {
    if (await copy.copy(value)) onCopied?.()
  }
  const copyButton = (
    <IconButton
      icon={copy.copied ? 'check' : 'copy'}
      size="sm"
      label={copyLabel}
      onClick={() => void copyValue()}
    />
  )
  const revealButton = secret ? (
    <IconButton
      icon={visible ? 'eye-off' : 'eye'}
      size="sm"
      label={visible ? 'Скрыть секрет' : 'Показать секрет'}
      tooltip={false}
      aria-pressed={visible}
      onClick={() => setVisible((current) => !current)}
    />
  ) : null
  return (
    <Field label={label} hint={hint} aside={multiline ? copyButton : undefined}>
      {multiline ? (
        <Textarea
          readOnly
          minRows={minRows}
          maxRows={maxRows}
          value={value}
          autoComplete="off"
          spellCheck={false}
          className={cn('font-mono', className)}
          onFocus={(event) => event.currentTarget.select()}
        />
      ) : (
        <Input
          readOnly
          type={visible ? 'text' : 'password'}
          value={value}
          autoComplete="off"
          data-lpignore={secret ? 'true' : undefined}
          data-1p-ignore={secret ? 'true' : undefined}
          spellCheck={false}
          leadingIcon={leadingIcon}
          className={cn('font-mono', className)}
          onFocus={(event) => event.currentTarget.select()}
          trailing={
            <>
              {revealButton}
              {copyButton}
            </>
          }
        />
      )}
    </Field>
  )
}
