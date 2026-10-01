import { RadioGroup as RadioGroupPrimitive } from 'radix-ui'
import { useRef } from 'react'
import { cn } from '@/shared/lib/cn'
import { Icon, type IconName } from '../icon'
import { useActiveIndicator } from '../tabs/use-active-indicator'
import { Tooltip } from '../tooltip/tooltip'

export interface SegmentedOption<T extends string = string> {
  value: T
  label: string
  icon?: IconName
  disabled?: boolean
}

export interface SegmentedControlProps<T extends string = string> {
  options: SegmentedOption<T>[]
  value: T
  onValueChange: (value: T) => void
  /** Подпись группы для скринридера: «Тема», «Масштаб». */
  'aria-label': string
  size?: 'sm' | 'md'
  /** Только иконки, подписи — в подсказках. */
  iconOnly?: boolean
  className?: string
}

/**
 * Переключатель режимов из 2–4 вариантов: вид, тема, масштаб. Семантика — радиогруппа:
 * стрелки меняют выбор. Подложка активного варианта мягко переезжает.
 */
export function SegmentedControl<T extends string>({
  options,
  value,
  onValueChange,
  size = 'md',
  iconOnly = false,
  className,
  'aria-label': ariaLabel,
}: SegmentedControlProps<T>) {
  const ref = useRef<HTMLDivElement>(null)
  const indicator = useActiveIndicator(ref, '[role="radio"][data-state="checked"]')
  return (
    <RadioGroupPrimitive.Root
      ref={ref}
      value={value}
      onValueChange={(next) => onValueChange(next as T)}
      orientation="horizontal"
      loop
      aria-label={ariaLabel}
      className={cn(
        'relative inline-flex items-center rounded-md border border-border bg-bg-subtle p-0.5',
        className,
      )}
    >
      <span
        aria-hidden="true"
        style={indicator.style}
        className={cn(
          'pointer-events-none absolute top-0 left-0 rounded-sm border border-border bg-surface-raised shadow-xs',
          'transition-[transform,width,opacity] duration-(--duration-slow) ease-soft',
          indicator.visible ? 'opacity-100' : 'opacity-0',
        )}
      />
      {options.map((option) => {
        const item = (
          <RadioGroupPrimitive.Item
            key={option.value}
            value={option.value}
            disabled={option.disabled}
            aria-label={iconOnly ? option.label : undefined}
            className={cn(
              'relative z-10 inline-flex cursor-pointer items-center justify-center gap-1.5 rounded-sm font-medium text-fg-muted outline-none',
              'transition-colors duration-(--duration-base) ease-soft hover:text-fg data-[state=checked]:text-fg',
              'focus-visible:outline-2 focus-visible:outline-offset-0 focus-visible:outline-focus-ring focus-visible:outline-solid',
              'disabled:pointer-events-none disabled:opacity-45',
              size === 'sm' ? 'h-6 text-xs' : 'h-7 text-sm',
              iconOnly ? (size === 'sm' ? 'w-6' : 'w-7') : size === 'sm' ? 'px-2' : 'px-2.5',
            )}
          >
            {option.icon && <Icon name={option.icon} size={size === 'sm' ? 14 : 16} />}
            {!iconOnly && option.label}
          </RadioGroupPrimitive.Item>
        )
        return iconOnly ? (
          <Tooltip key={option.value} content={option.label}>
            {item}
          </Tooltip>
        ) : (
          item
        )
      })}
    </RadioGroupPrimitive.Root>
  )
}
