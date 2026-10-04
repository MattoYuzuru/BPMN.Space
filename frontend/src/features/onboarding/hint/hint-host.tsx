import { useRouter } from '@tanstack/react-router'
import { useEffect, useRef } from 'react'
import { type Rect, toDomRect, useElementRect } from '@/shared/hooks/use-element-rect'
import { anchorSelector, TOUR_LAYER_ATTR } from '@/shared/lib/tour-anchors'
import { Beacon, Button, Popover, PopoverAnchor, PopoverContent, toast } from '@/shared/ui'
import { useAnchorElement } from '../anchor'
import { hideHint, useHintStore } from './store'

interface RouterLike {
  state: { location: { pathname: string } }
  subscribe: (event: string, listener: () => void) => () => void
}

/**
 * Хост подсказки-указателя. Закрывается по «Понятно», клику на сам элемент (подсказка
 * выполнила задачу), `Esc` и уходу с экрана. Грузится отдельным чанком (`HintHost` из `./index`).
 */
export default function HintHost() {
  const request = useHintStore((state) => state.current)
  const router = useRouter({ warn: false }) as unknown as RouterLike | undefined
  const requestId = request?.id
  const selector = request ? anchorSelector(request.anchor) : null
  const { element, timedOut } = useAnchorElement(selector, { enabled: Boolean(request) })
  const rect = useElementRect(element)
  const rectRef = useRef<Rect | null>(null)
  rectRef.current = rect
  const anchorRef = useRef({
    getBoundingClientRect: () => toDomRect(rectRef.current ?? { x: 0, y: 0, width: 0, height: 0 }),
  })

  // Подготовка экрана при показе.
  // biome-ignore lint/correctness/useExhaustiveDependencies: только новая подсказка
  useEffect(() => {
    if (!request) return
    try {
      request.prepare?.()
    } catch {
      // Подготовка — удобство; если не удалась, подсказка всё равно покажется или уйдёт в уведомление.
    }
  }, [requestId])

  // Якорь не найден — обычное уведомление.
  useEffect(() => {
    if (!request || !timedOut) return
    toast(request.text)
    hideHint()
  }, [request, timedOut])

  // Закрытие: клик по элементу, Esc, уход с экрана.
  useEffect(() => {
    if (!request || !element) return
    const close = () => hideHint()
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') hideHint()
    }
    const startPath = router?.state.location.pathname
    const unsubscribe = router?.subscribe('onResolved', () => {
      if (router.state.location.pathname !== startPath) hideHint()
    })
    element.addEventListener('click', close, { capture: true })
    document.addEventListener('keydown', onKey)
    return () => {
      element.removeEventListener('click', close, { capture: true })
      document.removeEventListener('keydown', onKey)
      unsubscribe?.()
    }
  }, [request, element, router])

  if (!request || !element || !rect) return null
  return (
    <>
      <Beacon target={rect} />
      <Popover open>
        <PopoverAnchor virtualRef={anchorRef} />
        <PopoverContent
          {...{ [TOUR_LAYER_ATTR]: '' }}
          side="bottom"
          sideOffset={14}
          aria-label="Подсказка"
          updatePositionStrategy="always"
          onOpenAutoFocus={(event) => event.preventDefault()}
          onCloseAutoFocus={(event) => event.preventDefault()}
          onInteractOutside={(event) => event.preventDefault()}
          onEscapeKeyDown={(event) => {
            event.preventDefault()
            hideHint()
          }}
          className="flex w-72 flex-col gap-3"
        >
          <p className="type-ui text-fg">{request.text}</p>
          <div className="flex justify-end">
            <Button variant="primary" size="sm" onClick={hideHint}>
              Понятно
            </Button>
          </div>
        </PopoverContent>
      </Popover>
    </>
  )
}
