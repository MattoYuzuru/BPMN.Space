import { useCallback, useEffect, useRef, useState } from 'react'
import { sentinelIndex, shouldLoadMore } from '@/shared/lib/infinite-scroll'

interface LoadMoreOptions {
  /** Сколько элементов уже загружено. */
  loaded: number
  hasNextPage: boolean
  isFetching: boolean
  fetchNextPage: () => unknown
  /** Колонок в сетке — сторож ставится на начало ряда. */
  columns?: number
}

/**
 * Бесконечная прокрутка на IntersectionObserver. Возвращает индекс элемента-сторожа (≈90 %
 * загруженного) и ref-колбэк для него: как только сторож показался в окне, грузится
 * следующая страница — до того, как пользователь упрётся в конец списка.
 */
export function useLoadMore({
  loaded,
  hasNextPage,
  isFetching,
  fetchNextPage,
  columns = 1,
}: LoadMoreOptions) {
  const index = sentinelIndex(loaded, columns)
  const [visible, setVisible] = useState(false)
  const observer = useRef<IntersectionObserver | null>(null)

  const ref = useCallback((node: Element | null) => {
    observer.current?.disconnect()
    observer.current = null
    setVisible(false)
    if (!node) return
    observer.current = new IntersectionObserver(
      (entries) => setVisible(entries.some((entry) => entry.isIntersecting)),
      { rootMargin: '0px 0px 120px 0px' },
    )
    observer.current.observe(node)
  }, [])

  useEffect(() => () => observer.current?.disconnect(), [])

  useEffect(() => {
    if (shouldLoadMore({ sentinelVisible: visible, hasNextPage, isFetching })) void fetchNextPage()
  }, [visible, hasNextPage, isFetching, fetchNextPage])

  return { sentinelIndex: index, sentinelRef: ref }
}

/** Число колонок CSS-сетки: следим за шириной контейнера. */
export function useGridColumns<T extends HTMLElement>() {
  const [columns, setColumns] = useState(1)
  const observer = useRef<ResizeObserver | null>(null)
  const ref = useCallback((node: T | null) => {
    observer.current?.disconnect()
    if (!node) return
    const measure = () => {
      const template = getComputedStyle(node).gridTemplateColumns
      setColumns(Math.max(1, template.split(' ').filter(Boolean).length))
    }
    measure()
    observer.current = new ResizeObserver(measure)
    observer.current.observe(node)
  }, [])
  useEffect(() => () => observer.current?.disconnect(), [])
  return { columns, gridRef: ref }
}
