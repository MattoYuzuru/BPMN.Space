import { createPortal } from 'react-dom'
import type { Rect } from '@/shared/hooks/use-element-rect'
import { useTourLayerTracking } from '@/shared/hooks/use-tour-layer'
import { cn } from '@/shared/lib/cn'
import { TOUR_LAYER_ATTR } from '@/shared/lib/tour-anchors'

export interface BeaconProps {
  /** Прямоугольник элемента в координатах окна (или контейнера при `position="absolute"`). */
  target: Rect | null
  pad?: number
  radius?: number
  /** fixed — поверх окна (подсказка); absolute — внутри контейнера (витрина). */
  position?: 'fixed' | 'absolute'
  className?: string
}

/**
 * Пульсирующее кольцо «Ток» вокруг элемента для подсказки-указателя, без затемнения экрана.
 * Три мягких импульса по 1,6 с, затем кольцо остаётся статичным. Кликам не мешает.
 * `prefers-reduced-motion` — без пульса.
 */
export function Beacon({
  target,
  pad = 4,
  radius = 8,
  position = 'fixed',
  className,
}: BeaconProps) {
  useTourLayerTracking()
  if (!target) return null
  const ring = (
    <div
      {...{ [TOUR_LAYER_ATTR]: '' }}
      aria-hidden="true"
      style={{
        left: target.x - pad,
        top: target.y - pad,
        width: target.width + pad * 2,
        height: target.height + pad * 2,
        borderRadius: radius + pad / 2,
      }}
      className={cn(
        'pointer-events-none z-55',
        position === 'fixed' ? 'fixed' : 'absolute',
        className,
      )}
    >
      <span className="absolute inset-0 rounded-[inherit] ring-2 ring-accent" />
      <span className="absolute inset-0 rounded-[inherit] bg-accent/10 ring-2 ring-accent animate-beacon motion-reduce:animate-none" />
    </div>
  )
  return position === 'fixed' ? createPortal(ring, document.body) : ring
}
