import { Select as SelectPrimitive } from 'radix-ui'
import { cn } from '@/shared/lib/cn'
import { useFieldControl } from '../field/field'
import { Icon, type IconName } from '../icon'
import { controlFrame, floatingSurface, menuItem } from '../styles'

export interface SelectOption {
  value: string
  label: string
  icon?: IconName
  disabled?: boolean
}

export interface SelectProps {
  options: SelectOption[]
  value?: string
  defaultValue?: string
  onValueChange?: (value: string) => void
  placeholder?: string
  size?: 'sm' | 'md'
  disabled?: boolean
  invalid?: boolean
  name?: string
  required?: boolean
  id?: string
  className?: string
  /** Подпись для скринридера, если Select стоит без Field. */
  'aria-label'?: string
}

/** Выбор одного значения из списка. Список рисуется нашим поповером, а не системным. */
export function Select({
  options,
  value,
  defaultValue,
  onValueChange,
  placeholder = 'Выберите',
  size = 'md',
  disabled,
  invalid,
  name,
  required,
  id,
  className,
  'aria-label': ariaLabel,
}: SelectProps) {
  const field = useFieldControl({ id, invalid, disabled })
  return (
    <SelectPrimitive.Root
      value={value}
      defaultValue={defaultValue}
      onValueChange={onValueChange}
      disabled={field.disabled}
      name={name}
      required={required}
    >
      <SelectPrimitive.Trigger
        id={field.id}
        aria-label={ariaLabel}
        aria-invalid={field['aria-invalid']}
        aria-describedby={field['aria-describedby']}
        data-invalid={field.invalid || undefined}
        data-disabled={field.disabled || undefined}
        className={cn(
          controlFrame({ size }),
          'group/select cursor-pointer justify-between text-left outline-none',
          'focus-visible:border-accent focus-visible:ring-3 focus-visible:ring-accent/15',
          'data-[state=open]:border-accent data-[state=open]:ring-3 data-[state=open]:ring-accent/15',
          'data-[placeholder]:text-fg-subtle',
          className,
        )}
      >
        <span className="flex min-w-0 items-center gap-2 truncate">
          <SelectPrimitive.Value placeholder={placeholder} />
        </span>
        <SelectPrimitive.Icon className="inline-flex text-fg-subtle transition-colors group-hover/select:text-fg-muted">
          <Icon name="selector" size={14} />
        </SelectPrimitive.Icon>
      </SelectPrimitive.Trigger>
      <SelectPrimitive.Portal>
        <SelectPrimitive.Content
          position="popper"
          sideOffset={6}
          collisionPadding={8}
          className={cn(
            floatingSurface,
            'max-h-(--radix-select-content-available-height) min-w-(--radix-select-trigger-width) overflow-hidden rounded-md',
          )}
        >
          <SelectPrimitive.ScrollUpButton className="flex h-6 items-center justify-center text-fg-subtle">
            <Icon name="chevron-up" size={14} />
          </SelectPrimitive.ScrollUpButton>
          <SelectPrimitive.Viewport className="p-1">
            {options.map((option) => (
              <SelectPrimitive.Item
                key={option.value}
                value={option.value}
                disabled={option.disabled}
                className={cn(menuItem, 'pr-8')}
              >
                {option.icon && <Icon name={option.icon} size={16} className="text-fg-muted" />}
                <SelectPrimitive.ItemText>{option.label}</SelectPrimitive.ItemText>
                <SelectPrimitive.ItemIndicator className="absolute right-2 inline-flex animate-fade-in text-accent-fg">
                  <Icon name="check" size={14} />
                </SelectPrimitive.ItemIndicator>
              </SelectPrimitive.Item>
            ))}
          </SelectPrimitive.Viewport>
          <SelectPrimitive.ScrollDownButton className="flex h-6 items-center justify-center text-fg-subtle">
            <Icon name="chevron-down" size={14} />
          </SelectPrimitive.ScrollDownButton>
        </SelectPrimitive.Content>
      </SelectPrimitive.Portal>
    </SelectPrimitive.Root>
  )
}
