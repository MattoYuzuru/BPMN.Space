import type { ReactNode } from 'react'
import { cn } from '@/shared/lib/cn'

interface ControlLabelProps {
  control: ReactNode
  controlId: string
  label: ReactNode
  description?: ReactNode
  descriptionId?: string
  disabled?: boolean
}

/** Подпись для флажка, радио и переключателя: вся строка кликабельна и подсвечивает контрол. */
export function ControlLabel({
  control,
  controlId,
  label,
  description,
  descriptionId,
  disabled,
}: ControlLabelProps) {
  return (
    <div
      className={cn('group/control flex items-start gap-2.5', disabled && 'opacity-60')}
      data-disabled={disabled || undefined}
    >
      <div className="flex h-5 shrink-0 items-center">{control}</div>
      <div className="flex min-w-0 flex-col gap-0.5">
        <label
          htmlFor={controlId}
          className={cn(
            'select-none text-sm text-fg',
            disabled ? 'cursor-not-allowed' : 'cursor-pointer',
          )}
        >
          {label}
        </label>
        {description && (
          <p id={descriptionId} className="type-caption text-fg-muted">
            {description}
          </p>
        )}
      </div>
    </div>
  )
}
