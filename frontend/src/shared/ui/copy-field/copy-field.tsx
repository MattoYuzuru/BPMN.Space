import { type ReactNode, useState } from 'react'
import { useCopy } from '@/shared/hooks/use-copy'
import { cn } from '@/shared/lib/cn'
import { Field } from '../field/field'
import type { IconName } from '../icon'
import { IconButton } from '../icon-button/icon-button'
import { Input } from '../input/input'
import { Textarea } from '../textarea/textarea'

export interface CopyFieldProps {
  /** Значение: адрес, токен, команда подключения. Копируется целиком. */
  value: string
  /** Подпись поля. */
  label: ReactNode
  /** Тост после успешного копирования. */
  copyMessage?: string
  /** Подпись кнопки копирования для скринридера. */
  copyLabel?: string
  hint?: ReactNode
  /** Многострочное значение — команда или текст запроса. */
  multiline?: boolean
  minRows?: number
  maxRows?: number
  /** Секрет: скрыт за кнопкой «показать», но копируется целиком. */
  secret?: boolean
  /** Иконка слева внутри поля. */
  leadingIcon?: IconName
  className?: string
}

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
  className,
}: CopyFieldProps) {
  const copy = useCopy(copyMessage)
  const [visible, setVisible] = useState(!secret)
  const copyButton = (
    <IconButton
      icon={copy.copied ? 'check' : 'copy'}
      size="sm"
      label={copyLabel}
      onClick={() => void copy.copy(value)}
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
          spellCheck={false}
          className={cn('font-mono', className)}
          onFocus={(event) => event.currentTarget.select()}
        />
      ) : (
        <Input
          readOnly
          type={visible ? 'text' : 'password'}
          value={value}
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
