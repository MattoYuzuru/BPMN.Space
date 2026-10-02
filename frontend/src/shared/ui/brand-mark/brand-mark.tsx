import { cn } from '@/shared/lib/cn'
import { Icon } from '../icon'

export interface BrandMarkProps {
  size?: 'sm' | 'md' | 'lg'
  className?: string
}

/** Знак продукта: схема на заливке Тока. В шапке, на пустых экранах и в 404. */
export function BrandMark({ size = 'md', className }: BrandMarkProps) {
  return (
    <span
      aria-hidden="true"
      className={cn(
        'grid shrink-0 place-items-center bg-accent text-fg-on-accent',
        'shadow-[inset_0_1px_0_oklch(1_0_0/0.18),var(--shadow-xs)]',
        size === 'sm' && 'size-6 rounded-sm',
        size === 'md' && 'size-7 rounded-md',
        size === 'lg' && 'size-11 rounded-lg',
        className,
      )}
    >
      <Icon name="diagram" size={size === 'lg' ? 24 : size === 'md' ? 16 : 14} />
    </span>
  )
}
