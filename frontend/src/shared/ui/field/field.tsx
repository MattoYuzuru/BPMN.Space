import { Label } from 'radix-ui'
import { createContext, type ReactNode, useContext, useId } from 'react'
import { cn } from '@/shared/lib/cn'
import { Icon } from '../icon'

interface FieldContextValue {
  controlId: string
  hintId?: string
  errorId?: string
  invalid: boolean
  disabled: boolean
}

const FieldContext = createContext<FieldContextValue | null>(null)

interface ControlInput {
  id?: string
  invalid?: boolean
  disabled?: boolean
  describedBy?: string
}

/**
 * Связывает контрол с Field: id для подписи, aria-describedby на подсказку и ошибку,
 * aria-invalid. Вне Field возвращает то, что передали.
 */
export function useFieldControl({ id, invalid, disabled, describedBy }: ControlInput) {
  const field = useContext(FieldContext)
  const describedByIds = [describedBy, field?.hintId, field?.errorId].filter(Boolean).join(' ')
  const isInvalid = Boolean(invalid ?? field?.invalid)
  return {
    id: id ?? field?.controlId,
    invalid: isInvalid,
    disabled: Boolean(disabled ?? field?.disabled),
    'aria-describedby': describedByIds || undefined,
    'aria-invalid': isInvalid || undefined,
  }
}

export interface FieldProps {
  label: ReactNode
  /** Подсказка под полем — только если без неё поле нельзя заполнить правильно. */
  hint?: ReactNode
  /** Текст ошибки. Поле получает aria-invalid и красную рамку. */
  error?: ReactNode
  /** Пометка «необязательно» рядом с подписью. Обязательные поля звёздочкой не помечаем. */
  optional?: boolean
  disabled?: boolean
  /** Элемент справа от подписи: счётчик символов, ссылка «Как заполнить». */
  aside?: ReactNode
  className?: string
  children: ReactNode
}

/** Подпись, поле и сообщение об ошибке — с правильными связями для доступности. */
export function Field({
  label,
  hint,
  error,
  optional,
  disabled = false,
  aside,
  className,
  children,
}: FieldProps) {
  const baseId = useId()
  const value: FieldContextValue = {
    controlId: `${baseId}-control`,
    hintId: hint ? `${baseId}-hint` : undefined,
    errorId: error ? `${baseId}-error` : undefined,
    invalid: Boolean(error),
    disabled,
  }
  return (
    <FieldContext.Provider value={value}>
      <div className={cn('flex flex-col gap-1.5', className)} data-disabled={disabled || undefined}>
        <div className="flex items-baseline justify-between gap-3">
          <Label.Root
            htmlFor={value.controlId}
            className="type-label text-fg data-[disabled]:opacity-60"
          >
            {label}
            {optional && <span className="ml-1.5 font-normal text-fg-subtle">необязательно</span>}
          </Label.Root>
          {aside && <div className="type-caption text-fg-subtle">{aside}</div>}
        </div>
        {children}
        {hint && !error && (
          <p id={value.hintId} className="type-caption text-fg-muted">
            {hint}
          </p>
        )}
        {error && (
          <p
            id={value.errorId}
            aria-live="polite"
            className="flex animate-fade-in items-center gap-1.5 type-caption text-danger-fg"
          >
            <Icon name="alert-circle" size={14} />
            {error}
          </p>
        )}
      </div>
    </FieldContext.Provider>
  )
}
