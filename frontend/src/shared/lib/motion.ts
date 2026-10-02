/**
 * Пресеты движения для motion (`m.*` внутри LazyMotion). Значения — те же токены, что в CSS
 * (`--ease-soft`, `--duration-*`), чтобы анимации motion и Tailwind не спорили между собой.
 * prefers-reduced-motion учитывает MotionConfig reducedMotion="user" в корне приложения.
 */
import type { Transition, Variants } from 'motion/react'

export const EASE_SOFT = [0.22, 1, 0.36, 1] as const
export const EASE_IN_SOFT = [0.32, 0, 0.67, 0] as const

export const DURATION = { fast: 0.12, base: 0.2, slow: 0.32 } as const

export const softTransition: Transition = { duration: DURATION.slow, ease: EASE_SOFT }

/** Появление элемента списка: снизу на 6px, выход короче входа. */
export const listItem: Variants = {
  initial: { opacity: 0, y: 6 },
  animate: { opacity: 1, y: 0, transition: softTransition },
  exit: { opacity: 0, y: -4, transition: { duration: DURATION.base, ease: EASE_IN_SOFT } },
}

/** Уход решённого вопроса: в сторону вкладки «Решено». */
export const resolvedExit: Variants = {
  initial: { opacity: 0, y: 6 },
  animate: { opacity: 1, y: 0, x: 0, transition: softTransition },
  exit: { opacity: 0, x: 24, transition: { duration: DURATION.slow, ease: EASE_IN_SOFT } },
}

/** Плавающая панель (ход прогона, карточка элемента схемы). */
export const floatingPanel: Variants = {
  initial: { opacity: 0, y: 8, scale: 0.98 },
  animate: { opacity: 1, y: 0, scale: 1, transition: softTransition },
  exit: {
    opacity: 0,
    y: 6,
    scale: 0.98,
    transition: { duration: DURATION.base, ease: EASE_IN_SOFT },
  },
}

/** Задержка появления по индексу для «каскада» в сетке карточек (не больше ~0,3 с суммарно). */
export function staggerDelay(index: number, step = 0.03, max = 0.3): number {
  return Math.min(index * step, max)
}
