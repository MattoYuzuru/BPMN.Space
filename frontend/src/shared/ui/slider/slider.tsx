import { Slider as SliderPrimitive } from 'radix-ui'
import { cn } from '@/shared/lib/cn'
import { formatNumber } from '@/shared/lib/format'

export interface SliderProps {
  value: number
  /** Новое значение во время перетаскивания и нажатий клавиш. */
  onValueChange?: (value: number) => void
  /** Значение зафиксировано (отпустили бегунок, отпустили клавишу) — момент перемотки. */
  onValueCommit?: (value: number) => void
  min?: number
  max?: number
  step?: number
  /** Подпись для скринридера: «Позиция записи». */
  label: string
  /** Формат значения справа и aria-valuetext: время записи вместо секунд. */
  formatValue?: (value: number) => string
  /** Показывать текущее значение справа от полосы. */
  showValue?: boolean
  disabled?: boolean
  className?: string
}

/**
 * Один бегунок по шкале: перемотка записи, выбор длительности. Клавиатура — стрелки, Home/End,
 * PageUp/PageDown (Radix). Значение читается скринридером в формате `formatValue`.
 */
export function Slider({
  value,
  onValueChange,
  onValueCommit,
  min = 0,
  max = 100,
  step = 1,
  label,
  formatValue,
  showValue = false,
  disabled = false,
  className,
}: SliderProps) {
  const readout = formatValue ? formatValue(value) : formatNumber(value)
  return (
    <div className={cn('flex items-center gap-3', className)}>
      <SliderPrimitive.Root
        value={[value]}
        min={min}
        max={max}
        step={step}
        disabled={disabled}
        onValueChange={([next]) => {
          if (next !== undefined) onValueChange?.(next)
        }}
        onValueCommit={([next]) => {
          if (next !== undefined) onValueCommit?.(next)
        }}
        className={cn(
          'group/slider relative flex h-5 w-full min-w-0 flex-1 touch-none select-none items-center',
          'data-[disabled]:cursor-not-allowed',
        )}
      >
        <SliderPrimitive.Track className="relative h-1 w-full grow overflow-hidden rounded-full bg-pressed transition-colors duration-base ease-soft group-data-[disabled]/slider:opacity-50">
          <SliderPrimitive.Range className="absolute h-full bg-accent" />
        </SliderPrimitive.Track>
        <SliderPrimitive.Thumb
          aria-label={label}
          aria-valuetext={readout}
          className={cn(
            'block size-3.5 shrink-0 rounded-full border-2 border-accent bg-surface shadow-sm outline-none',
            'transition-[box-shadow,background-color] duration-base ease-soft',
            'hover:ring-3 hover:ring-accent/15',
            'focus-visible:ring-3 focus-visible:ring-focus-ring/40',
            'data-[disabled]:cursor-not-allowed data-[disabled]:opacity-50',
          )}
        />
      </SliderPrimitive.Root>
      {showValue && (
        <span
          className="type-caption min-w-10 shrink-0 text-right text-fg-muted tabular-nums"
          data-numeric
        >
          {readout}
        </span>
      )}
    </div>
  )
}
