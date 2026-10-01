import { cn } from '@/shared/lib/cn'

export interface GridBackdropProps {
  /** grid — линии чертёжной сетки (холст, пустые состояния), dots — точки (под плотным содержимым). */
  pattern?: 'grid' | 'dots'
  /** Затухание к краям. none — для холста во всю область. */
  fade?: 'radial' | 'none'
  /** Мягкое свечение тока в центре — для главного пустого состояния экрана. */
  glow?: boolean
  className?: string
}

/**
 * Фирменный приём «Сетка-подложка»: тонкая чертёжная сетка, как у холста BPMN.
 * Кладётся под содержимое (родитель — relative isolate), не перехватывает клики.
 */
export function GridBackdrop({
  pattern = 'grid',
  fade = 'radial',
  glow = false,
  className,
}: GridBackdropProps) {
  return (
    <div aria-hidden="true" className={cn('pointer-events-none absolute inset-0 -z-10', className)}>
      <div
        className={cn(
          'absolute inset-0',
          pattern === 'grid' ? 'pattern-grid' : 'pattern-dots',
          fade === 'radial' && 'mask-fade-radial',
        )}
      />
      {glow && (
        <div className="absolute inset-0 bg-[radial-gradient(40%_36%_at_50%_42%,color-mix(in_oklab,var(--color-accent)_9%,transparent),transparent)]" />
      )}
    </div>
  )
}
