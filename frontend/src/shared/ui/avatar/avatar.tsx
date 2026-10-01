import { Avatar as AvatarPrimitive } from 'radix-ui'
import { cn } from '@/shared/lib/cn'

const sizes = {
  sm: 'size-5 text-2xs',
  md: 'size-6 text-2xs',
  lg: 'size-8 text-xs',
} as const

/** «Финансовый отдел» → «ФО», «Заявитель» → «З». */
export function initials(name: string): string {
  const words = name.trim().split(/\s+/).filter(Boolean)
  const letters = words.slice(0, 2).map((word) => word[0]?.toUpperCase() ?? '')
  return letters.join('')
}

export interface AvatarProps {
  /** Имя человека или роли — из него строятся инициалы и подпись для скринридера. */
  name: string
  src?: string
  size?: keyof typeof sizes
  className?: string
}

/** Аватар участника или роли процесса. Без картинки — инициалы на нейтральной подложке. */
export function Avatar({ name, src, size = 'md', className }: AvatarProps) {
  return (
    <AvatarPrimitive.Root
      className={cn(
        'relative inline-flex shrink-0 select-none items-center justify-center overflow-hidden rounded-full',
        'border border-border bg-bg-subtle font-medium text-fg-muted',
        sizes[size],
        className,
      )}
    >
      {src && <AvatarPrimitive.Image src={src} alt={name} className="size-full object-cover" />}
      <AvatarPrimitive.Fallback aria-label={name} className="leading-none">
        {initials(name)}
      </AvatarPrimitive.Fallback>
    </AvatarPrimitive.Root>
  )
}
