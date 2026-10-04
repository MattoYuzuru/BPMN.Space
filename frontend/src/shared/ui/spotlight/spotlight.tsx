import { animate, useReducedMotion } from 'motion/react'
import { useEffect, useId, useRef } from 'react'
import { createPortal } from 'react-dom'
import type { Rect } from '@/shared/hooks/use-element-rect'
import { useTourLayerTracking } from '@/shared/hooks/use-tour-layer'
import { cn } from '@/shared/lib/cn'
import { DURATION, EASE_SOFT } from '@/shared/lib/motion'
import { TOUR_LAYER_ATTR } from '@/shared/lib/tour-anchors'

export type { Rect } from '@/shared/hooks/use-element-rect'

export interface SpotlightProps {
  /** Прямоугольник целевого элемента в координатах окна (или контейнера при `position="absolute"`). Нет — затемнён весь экран. */
  target: Rect | null
  /** Отступ выреза от элемента, px. */
  pad?: number
  /** Радиус выреза, px (по умолчанию как у кнопки — `radius-md`). */
  radius?: number
  /** Затемнять экран. false — только кольцо у элемента (у окна своё затемнение). */
  dim?: boolean
  /** Перехватывать клики вне выреза. false — клики везде (шаг «подвигайте схему»). */
  block?: boolean
  /** Перехватчик на весь экран, без свободного выреза (ждём появления элемента, вырез остаётся для вида). */
  blockAll?: boolean
  /** Меняется на каждом шаге: при смене вырез плавно переезжает, а не прыгает. */
  transitionKey?: string
  /** Клик по перехватчику: карточка подсвечивает рамку, чтобы было видно, где продолжать. */
  onBlockedClick?: () => void
  /** Текущий (анимируемый) прямоугольник выреза с отступом — карточка едет следом. */
  onFrame?: (rect: Rect | null) => void
  /** fixed — на весь экран (тур); absolute — внутри контейнера (витрина). */
  position?: 'fixed' | 'absolute'
  className?: string
}

function samePlace(a: Rect, b: Rect) {
  return a.x === b.x && a.y === b.y && a.width === b.width && a.height === b.height
}

function lerp(a: number, b: number, t: number) {
  return a + (b - a) * t
}

function padded(rect: Rect, pad: number): Rect {
  return {
    x: rect.x - pad,
    y: rect.y - pad,
    width: rect.width + pad * 2,
    height: rect.height + pad * 2,
  }
}

/**
 * Затемнение экрана с вырезом вокруг одного элемента.
 *
 * Визуальный слой — один SVG с `pointer-events: none` (вырез сделан маской, поэтому на события
 * не влияет). Клики перехватывают четыре прозрачных блока вокруг выреза: сам вырез свободен,
 * клик проходит к элементу. При смене `transitionKey` вырез плавно переезжает и меняет размер
 * (`DURATION.slow`, `EASE_SOFT`, без пружин), затемнение при этом не мигает; при
 * `prefers-reduced-motion` смена мгновенная. Слой помечен `data-tour-layer`.
 */
export function Spotlight({
  target,
  pad = 6,
  radius = 8,
  dim = true,
  block = true,
  blockAll = false,
  transitionKey,
  onBlockedClick,
  onFrame,
  position = 'fixed',
  className,
}: SpotlightProps) {
  useTourLayerTracking()
  const maskId = useId()
  const reduced = useReducedMotion()
  const holeRef = useRef<SVGRectElement>(null)
  const ringRef = useRef<HTMLDivElement>(null)
  const onFrameRef = useRef(onFrame)
  onFrameRef.current = onFrame

  // Отображаемый и целевой прямоугольники и прогресс переезда между ними.
  const shown = useRef<Rect | null>(null)
  const from = useRef<Rect | null>(null)
  const to = useRef<Rect | null>(null)
  const progress = useRef(1)
  const lastKey = useRef(transitionKey)
  // Смена шага ждёт, пока вырез поедет на новое место (новый элемент может появиться позже).
  const glideSince = useRef<number | null>(null)
  const controls = useRef<{ stop: () => void } | null>(null)

  const paint = (rect: Rect | null) => {
    shown.current = rect
    const hole = holeRef.current
    const ring = ringRef.current
    if (hole) {
      hole.setAttribute('x', String(rect?.x ?? 0))
      hole.setAttribute('y', String(rect?.y ?? 0))
      hole.setAttribute('width', String(rect?.width ?? 0))
      hole.setAttribute('height', String(rect?.height ?? 0))
    }
    if (ring) {
      ring.style.opacity = rect ? '1' : '0'
      if (rect) {
        ring.style.transform = `translate(${rect.x}px, ${rect.y}px)`
        ring.style.width = `${rect.width}px`
        ring.style.height = `${rect.height}px`
      }
    }
    onFrameRef.current?.(rect)
  }

  const targetX = target?.x
  const targetY = target?.y
  const targetW = target?.width
  const targetH = target?.height
  const hasTarget = target !== null

  // biome-ignore lint/correctness/useExhaustiveDependencies: зависимости — координаты цели; paint и ref-объекты стабильны
  useEffect(() => {
    const next =
      hasTarget && targetX !== undefined
        ? padded({ x: targetX, y: targetY ?? 0, width: targetW ?? 0, height: targetH ?? 0 }, pad)
        : null
    to.current = next
    if (lastKey.current !== transitionKey) {
      lastKey.current = transitionKey
      glideSince.current = Date.now()
    }
    const glide = glideSince.current !== null && Date.now() - glideSince.current < 6000
    const current = shown.current

    if (glide && next && !current) glideSince.current = null
    if (glide && current && next && !reduced && !samePlace(current, next)) {
      glideSince.current = null
      controls.current?.stop()
      from.current = current
      progress.current = 0
      controls.current = animate(0, 1, {
        duration: DURATION.slow,
        ease: EASE_SOFT,
        onUpdate: (t) => {
          progress.current = t
          const start = from.current
          const end = to.current
          if (!start || !end) return
          paint({
            x: lerp(start.x, end.x, t),
            y: lerp(start.y, end.y, t),
            width: lerp(start.width, end.width, t),
            height: lerp(start.height, end.height, t),
          })
        },
        onComplete: () => {
          progress.current = 1
        },
      })
      return
    }
    if (progress.current < 1 && next && from.current) {
      // Идёт переезд, а цель сдвинулась (прокрутка): тянемся к новой цели, не перезапуская.
      const start = from.current
      const t = progress.current
      paint({
        x: lerp(start.x, next.x, t),
        y: lerp(start.y, next.y, t),
        width: lerp(start.width, next.width, t),
        height: lerp(start.height, next.height, t),
      })
      return
    }
    controls.current?.stop()
    progress.current = 1
    paint(next)
  }, [hasTarget, targetX, targetY, targetW, targetH, pad, transitionKey, reduced])

  useEffect(() => () => controls.current?.stop(), [])

  const box = target ? padded(target, pad) : null
  const blockers = block || blockAll ? blockerRects(blockAll ? null : box) : []

  const layer = (
    <div
      {...{ [TOUR_LAYER_ATTR]: '' }}
      className={cn(
        'pointer-events-none inset-0 z-60',
        position === 'fixed' ? 'fixed' : 'absolute overflow-hidden rounded-[inherit]',
        className,
      )}
    >
      {/* SVG не размонтируем: вырез хранит координаты, а при dim=false слой просто скрыт. */}
      {
        <svg
          aria-hidden="true"
          className={cn('pointer-events-none absolute inset-0 size-full', !dim && 'invisible')}
        >
          <defs>
            <mask id={maskId}>
              <rect width="100%" height="100%" fill="white" />
              <rect ref={holeRef} rx={radius} ry={radius} fill="black" />
            </mask>
          </defs>
          <rect width="100%" height="100%" className="fill-scrim" mask={`url(#${maskId})`} />
        </svg>
      }
      <div
        ref={ringRef}
        aria-hidden="true"
        style={{ borderRadius: radius + 2 }}
        className="pointer-events-none absolute top-0 left-0 opacity-0 shadow-glow ring-2 ring-accent/50"
      />
      {blockers.map((style) => (
        <div
          key={style.key}
          aria-hidden="true"
          data-tour-blocker=""
          style={style.css}
          className="pointer-events-auto absolute"
          onClick={onBlockedClick}
          onContextMenu={(event) => event.preventDefault()}
        />
      ))}
    </div>
  )
  // Слой окна — у корня документа: предки с isolate или transform не должны запирать z-индексы.
  return position === 'fixed' ? createPortal(layer, document.body) : layer
}

/** Четыре блока вокруг выреза (сверху, снизу, слева, справа) или один на весь экран. */
function blockerRects(box: Rect | null) {
  if (!box) return [{ key: 'all', css: { inset: 0 } }]
  const right = box.x + box.width
  const bottom = box.y + box.height
  return [
    { key: 'top', css: { top: 0, left: 0, right: 0, height: Math.max(box.y, 0) } },
    { key: 'bottom', css: { top: bottom, left: 0, right: 0, bottom: 0 } },
    { key: 'left', css: { top: box.y, left: 0, width: Math.max(box.x, 0), height: box.height } },
    { key: 'right', css: { top: box.y, left: right, right: 0, height: box.height } },
  ]
}
