import { useCallback, useEffect, useRef, useState } from 'react'

/** Значение, которое обновляется не раньше чем через `delay` мс после последнего изменения. */
export function useDebouncedValue<T>(value: T, delay: number): T {
  const [debounced, setDebounced] = useState(value)
  useEffect(() => {
    const timer = setTimeout(() => setDebounced(value), delay)
    return () => clearTimeout(timer)
  }, [value, delay])
  return debounced
}

/**
 * Отложенный вызов: срабатывает через `delay` мс после последнего вызова.
 * `flush` выполняет отложенный вызов сразу (например, при уходе со страницы).
 */
export function useDebouncedCallback<A extends unknown[]>(
  callback: (...args: A) => void,
  delay: number,
) {
  const callbackRef = useRef(callback)
  callbackRef.current = callback
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined)
  const pending = useRef<A | null>(null)

  const cancel = useCallback(() => {
    clearTimeout(timer.current)
    pending.current = null
  }, [])

  const flush = useCallback(() => {
    clearTimeout(timer.current)
    if (pending.current) {
      const args = pending.current
      pending.current = null
      callbackRef.current(...args)
    }
  }, [])

  const run = useCallback(
    (...args: A) => {
      pending.current = args
      clearTimeout(timer.current)
      timer.current = setTimeout(flush, delay)
    },
    [delay, flush],
  )

  useEffect(() => flush, [flush])
  return { run, flush, cancel }
}
