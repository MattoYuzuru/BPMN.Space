/**
 * Бесконечная прокрутка: следующую страницу начинаем грузить, когда пользователь дочитал
 * примерно 90 % загруженного. Для этого перед элементом с индексом `sentinelIndex` ставится
 * невидимый «сторож» (IntersectionObserver): как только он показался в окне, грузим дальше.
 * Порог считается от числа загруженных элементов, а не от высоты страницы, — так он не зависит
 * от ширины окна и числа колонок сетки.
 */
export const PREFETCH_THRESHOLD = 0.9

/** Индекс элемента, перед которым стоит сторож. Для сетки округляется вниз до начала ряда. */
export function sentinelIndex(loaded: number, columns = 1, threshold = PREFETCH_THRESHOLD): number {
  if (loaded <= 0) return 0
  const raw = Math.floor(loaded * threshold)
  const rowStart = raw - (raw % Math.max(1, columns))
  return Math.min(Math.max(rowStart, 0), loaded - 1)
}

/** Нужно ли грузить следующую страницу. */
export function shouldLoadMore(state: {
  sentinelVisible: boolean
  hasNextPage: boolean
  isFetching: boolean
}): boolean {
  return state.sentinelVisible && state.hasNextPage && !state.isFetching
}
