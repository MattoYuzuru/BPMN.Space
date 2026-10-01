import { Switch as SwitchPrimitive } from 'radix-ui'
import { type ComponentProps, type ReactNode, useId } from 'react'
import { cn } from '@/shared/lib/cn'
import { ControlLabel } from '../checkbox/control-label'

export interface SwitchProps extends ComponentProps<typeof SwitchPrimitive.Root> {
  label?: ReactNode
  description?: ReactNode
}

/** Переключатель настройки, которая применяется сразу (без кнопки «Сохранить»). */
export function Switch({ label, description, id, className, disabled, ...props }: SwitchProps) {
  const autoId = useId()
  const controlId = id ?? autoId
  const descriptionId = description ? `${controlId}-description` : undefined
  const control = (
    <SwitchPrimitive.Root
      id={controlId}
      disabled={disabled}
      aria-describedby={descriptionId}
      className={cn(
        'group/switch inline-flex h-4 w-7 shrink-0 cursor-pointer items-center rounded-full p-0.5',
        'bg-control/45 shadow-[inset_0_1px_1px_oklch(0_0_0/0.06)]',
        'transition-colors duration-base ease-soft',
        'hover:bg-control/60 group-hover/control:bg-control/60',
        'data-[state=checked]:bg-accent data-[state=checked]:hover:bg-accent-hover',
        'disabled:cursor-not-allowed disabled:opacity-45',
        className,
      )}
      {...props}
    >
      <SwitchPrimitive.Thumb className="block size-3 rounded-full bg-fg-on-accent shadow-[0_1px_2px_oklch(0_0_0/0.2)] transition-transform duration-slow ease-soft data-[state=checked]:translate-x-3" />
    </SwitchPrimitive.Root>
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
