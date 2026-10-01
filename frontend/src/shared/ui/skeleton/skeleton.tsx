import { cn } from '@/shared/lib/cn'

/**
 * Заглушка формы будущего содержимого. Загрузку областей показываем только так —
 * спиннеры для областей запрещены. Контейнер со скелетонами помечайте aria-busy="true".
 */
export function Skeleton({ className }: { className?: string }) {
  return <div aria-hidden="true" className={cn('skeleton-shimmer h-4 rounded-sm', className)} />
}

const WIDTHS = ['w-full', 'w-11/12', 'w-4/5', 'w-2/3', 'w-3/4']

/** Абзац из нескольких строк разной длины; последняя короче. */
export function SkeletonText({ lines = 3, className }: { lines?: number; className?: string }) {
  return (
    <div aria-hidden="true" className={cn('flex flex-col gap-2', className)}>
      {Array.from({ length: lines }, (_, index) => (
        <Skeleton
          // biome-ignore lint/suspicious/noArrayIndexKey: строки-заглушки без идентичности
          key={index}
          className={cn('h-3', index === lines - 1 ? 'w-3/5' : WIDTHS[index % WIDTHS.length])}
        />
      ))}
    </div>
  )
}
