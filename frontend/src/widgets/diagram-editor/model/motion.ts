import { cubicBezier, parseCubicBezier, parseDuration } from './viewbox'

/** Значения контракта дизайн-системы на случай, если токены ещё не подключены. */
const DEFAULT_CURVE: [number, number, number, number] = [0.22, 1, 0.36, 1]
const DEFAULT_DURATION = 320

export interface Motion {
  /** 0 — без анимации (prefers-reduced-motion). */
  duration: number
  easing: (t: number) => number
}

/** Движение по токенам `--ease-soft` и `--duration-slow` с учётом prefers-reduced-motion. */
export function readMotion(element: Element): Motion {
  const style = getComputedStyle(element)
  const reduced = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches ?? false
  const curve = parseCubicBezier(style.getPropertyValue('--ease-soft')) ?? DEFAULT_CURVE
  const duration = parseDuration(style.getPropertyValue('--duration-slow')) ?? DEFAULT_DURATION
  return { duration: reduced ? 0 : duration, easing: cubicBezier(...curve) }
}

/** Покадровая анимация от 0 до 1. Возвращает функцию отмены. */
export function animate(motion: Motion, onFrame: (progress: number) => void): () => void {
  if (motion.duration <= 0) {
    onFrame(1)
    return () => {}
  }
  let frame = 0
  const start = performance.now()
  const tick = (now: number) => {
    const linear = Math.min(1, (now - start) / motion.duration)
    onFrame(motion.easing(linear))
    if (linear < 1) frame = requestAnimationFrame(tick)
  }
  frame = requestAnimationFrame(tick)
  return () => cancelAnimationFrame(frame)
}
