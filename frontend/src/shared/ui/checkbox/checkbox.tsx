import { Checkbox as CheckboxPrimitive } from 'radix-ui'
import { type ComponentProps, type ReactNode, useId } from 'react'
import { cn } from '@/shared/lib/cn'
import { useFieldControl } from '../field/field'
import { ControlLabel } from './control-label'

export interface CheckboxProps extends ComponentProps<typeof CheckboxPrimitive.Root> {
  /** Подпись справа. Кликабельна вместе с квадратом. */
  label?: ReactNode
  /** Вторая строка под подписью — только если подпись сама не объясняет выбор. */
  description?: ReactNode
  invalid?: boolean
}

/** Флажок. Состояние «частично» — checked="indeterminate". Галочка прорисовывается штрихом. */
export function Checkbox({
  label,
  description,
  invalid,
  disabled,
  id,
  className,
  'aria-describedby': describedBy,
  ...props
}: CheckboxProps) {
  const autoId = useId()
  const descriptionId = description ? `${autoId}-description` : undefined
  const field = useFieldControl({
    id,
    invalid,
    disabled,
    describedBy: [describedBy, descriptionId].filter(Boolean).join(' ') || undefined,
  })
  const controlId = field.id ?? autoId

  const control = (
    <CheckboxPrimitive.Root
      id={controlId}
      disabled={field.disabled}
      aria-invalid={field['aria-invalid']}
      aria-describedby={field['aria-describedby']}
      className={cn(
        'group/checkbox relative inline-grid size-4 shrink-0 cursor-pointer place-items-center rounded-xs border border-control bg-surface text-fg-on-accent shadow-xs',
        'transition-[background-color,border-color,box-shadow] duration-(--duration-base) ease-soft',
        'hover:border-fg-muted group-hover/control:border-fg-muted',
        'data-[state=checked]:border-accent data-[state=checked]:bg-accent data-[state=indeterminate]:border-accent data-[state=indeterminate]:bg-accent',
        'data-[state=checked]:hover:border-accent-hover data-[state=checked]:hover:bg-accent-hover',
        'aria-invalid:border-danger disabled:cursor-not-allowed disabled:opacity-45',
        className,
      )}
      {...props}
    >
      <svg
        viewBox="0 0 16 16"
        fill="none"
        aria-hidden="true"
        className="col-start-1 row-start-1 size-4"
      >
        <path
          d="M4 8.5 6.75 11.25 12 5.5"
          stroke="currentColor"
          strokeWidth="1.75"
          strokeLinecap="round"
          strokeLinejoin="round"
          className="transition-[stroke-dashoffset] delay-[40ms] duration-(--duration-slow) ease-soft [stroke-dasharray:12] [stroke-dashoffset:12] group-data-[state=checked]/checkbox:[stroke-dashoffset:0]"
        />
      </svg>
      <svg
        viewBox="0 0 16 16"
        fill="none"
        aria-hidden="true"
        className="col-start-1 row-start-1 size-4"
      >
        <path
          d="M4.5 8h7"
          stroke="currentColor"
          strokeWidth="1.75"
          strokeLinecap="round"
          className="transition-[stroke-dashoffset] duration-(--duration-base) ease-soft [stroke-dasharray:7] [stroke-dashoffset:7] group-data-[state=indeterminate]/checkbox:[stroke-dashoffset:0]"
        />
      </svg>
    </CheckboxPrimitive.Root>
  )

  if (!label) return control
  return (
    <ControlLabel
      control={control}
      controlId={controlId}
      label={label}
      description={description}
      descriptionId={descriptionId}
      disabled={field.disabled}
    />
  )
}
