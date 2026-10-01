import { type ComponentProps, type PointerEvent, type ReactNode, useRef } from 'react'
import { cn } from '@/shared/lib/cn'
import { mergeRefs } from '@/shared/lib/merge-refs'
import { useFieldControl } from '../field/field'
import { Icon, type IconName } from '../icon'
import { controlFrame } from '../styles'

export interface InputProps extends Omit<ComponentProps<'input'>, 'size'> {
  size?: 'sm' | 'md'
  /** Иконка внутри поля слева (поиск, ссылка). */
  leadingIcon?: IconName
  /** Элемент справа: Kbd, IconButton очистки, единица измерения. */
  trailing?: ReactNode
  invalid?: boolean
  /** Классы рамки (ширина, отступы). className применяется к самому <input>. */
  wrapperClassName?: string
}

/** Однострочное поле. Внутри Field получает подпись, подсказку и ошибку автоматически. */
export function Input({
  size = 'md',
  leadingIcon,
  trailing,
  invalid,
  disabled,
  id,
  className,
  wrapperClassName,
  ref,
  'aria-describedby': describedBy,
  ...props
}: InputProps) {
  const inputRef = useRef<HTMLInputElement>(null)
  const field = useFieldControl({ id, invalid, disabled, describedBy })
  // Клик по рамке или иконке ставит курсор в поле, как в нативном контроле.
  const focusInput = (event: PointerEvent<HTMLDivElement>) => {
    if (event.target !== inputRef.current) {
      event.preventDefault()
      inputRef.current?.focus()
    }
  }
  return (
    <div
      data-invalid={field.invalid || undefined}
      data-disabled={field.disabled || undefined}
      onPointerDown={focusInput}
      className={cn(controlFrame({ size }), 'cursor-text', wrapperClassName)}
    >
      {leadingIcon && (
        <Icon name={leadingIcon} size={size === 'sm' ? 14 : 16} className="text-fg-subtle" />
      )}
      <input
        ref={mergeRefs(inputRef, ref)}
        id={field.id}
        disabled={field.disabled}
        aria-invalid={field['aria-invalid']}
        aria-describedby={field['aria-describedby']}
        className={cn(
          'h-full min-w-0 flex-1 bg-transparent text-fg outline-none placeholder:text-fg-subtle',
          'disabled:cursor-not-allowed [&::-webkit-search-cancel-button]:hidden',
          className,
        )}
        {...props}
      />
      {trailing && <div className="-mr-1 flex shrink-0 items-center gap-1">{trailing}</div>}
    </div>
  )
}
