import { type ComponentType, lazy, Suspense, useState } from 'react'
import { cn } from '@/shared/lib/cn'
import type { GridLensCanvasProps } from './grid-lens-canvas'

export interface GridBackdropProps {
  /** grid — линии чертёжной сетки (холст, пустые состояния), dots — точки (под плотным содержимым). */
  pattern?: 'grid' | 'dots'
  /** Затухание к краям. none — для холста во всю область. */
  fade?: 'radial' | 'none'
  /** Мягкое свечение тока в центре — для главного пустого состояния экрана. */
  glow?: boolean
  /**
   * Живая линза под курсором (WebGL2, отдельный ленивый чанк). Только для первого экрана и только
   * с pattern="grid"; без мыши, при «сократить движение» и без WebGL2 остаётся обычная сетка.
   * Элементы с data-lens-block гасят линзу под собой.
   */
  interactive?: boolean
  className?: string
}

// Чанк с WebGL-кодом: при сбое загрузки остаётся CSS-сетка, а не падает экран.
type LensModule = { default: ComponentType<GridLensCanvasProps> }
const GridLensCanvas = lazy(() =>
  import('./grid-lens-canvas').then(
    (module): LensModule => module,
    (): LensModule => ({ default: () => null }),
  ),
)

/**
 * Фирменный приём «Сетка-подложка»: тонкая чертёжная сетка, как у холста BPMN.
 * Кладётся под содержимое (родитель — relative isolate), не перехватывает клики.
 */
export function GridBackdrop({
  pattern = 'grid',
  fade = 'radial',
  glow = false,
  interactive = false,
  className,
}: GridBackdropProps) {
  const [lensActive, setLensActive] = useState(false)
  const withLens = interactive && pattern === 'grid'
  const mask = fade === 'radial' && 'mask-fade-radial'
  return (
    <div aria-hidden="true" className={cn('pointer-events-none absolute inset-0 -z-10', className)}>
      <div
        className={cn(
          'absolute inset-0',
          pattern === 'grid' ? 'pattern-grid' : 'pattern-dots',
          mask,
          withLens && lensActive && 'invisible',
        )}
      />
      {withLens && (
        <Suspense fallback={null}>
          <GridLensCanvas
            onActiveChange={setLensActive}
            className={cn('absolute inset-0 size-full', mask)}
          />
        </Suspense>
      )}
      {glow && (
        <div className="absolute inset-0 bg-[radial-gradient(40%_36%_at_50%_42%,color-mix(in_oklab,var(--color-accent)_9%,transparent),transparent)]" />
      )}
    </div>
  )
}
