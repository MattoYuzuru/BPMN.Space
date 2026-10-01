import { RadioGroup as RadioGroupPrimitive } from 'radix-ui'
import { type ComponentProps, type ReactNode, useId } from 'react'
import { cn } from '@/shared/lib/cn'
import { ControlLabel } from '../checkbox/control-label'

export type RadioGroupProps = ComponentProps<typeof RadioGroupPrimitive.Root>

/** Группа взаимоисключающих вариантов. Стрелки переключают выбор, Tab уходит из группы. */
export function RadioGroup({ className, orientation = 'vertical', ...props }: RadioGroupProps) {
  return (
    <RadioGroupPrimitive.Root
      orientation={orientation}
      className={cn(
        'flex',
        orientation === 'vertical' ? 'flex-col gap-2.5' : 'flex-row flex-wrap gap-x-5 gap-y-2',
        className,
      )}
      {...props}
    />
  )
}

export interface RadioGroupItemProps extends ComponentProps<typeof RadioGroupPrimitive.Item> {
  label?: ReactNode
  description?: ReactNode
}

export function RadioGroupItem({
  label,
  description,
  id,
  className,
  disabled,
  ...props
}: RadioGroupItemProps) {
  const autoId = useId()
  const controlId = id ?? autoId
  const descriptionId = description ? `${controlId}-description` : undefined
  const control = (
    <RadioGroupPrimitive.Item
      id={controlId}
      disabled={disabled}
      aria-describedby={descriptionId}
      className={cn(
        'group/radio relative grid size-4 shrink-0 cursor-pointer place-items-center rounded-full border border-control bg-surface shadow-xs',
        'transition-[background-color,border-color] duration-(--duration-base) ease-soft',
        'hover:border-fg-muted group-hover/control:border-fg-muted',
        'data-[state=checked]:border-accent data-[state=checked]:bg-accent data-[state=checked]:hover:bg-accent-hover',
        'disabled:cursor-not-allowed disabled:opacity-45',
        className,
      )}
      {...props}
    >
      <span
        aria-hidden="true"
        className="size-1.5 scale-0 rounded-full bg-fg-on-accent transition-transform duration-(--duration-slow) ease-soft group-data-[state=checked]/radio:scale-100"
      />
    </RadioGroupPrimitive.Item>
  )
  if (!label) return control
  return (
    <ControlLabel
      control={control}
      controlId={controlId}
      label={label}
      description={description}
      descriptionId={descriptionId}
      disabled={disabled}
    />
  )
}
