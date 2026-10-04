import { Popover as PopoverPrimitive } from 'radix-ui'
import {
  type KeyboardEvent,
  type ReactNode,
  type RefObject,
  useCallback,
  useEffect,
  useId,
  useRef,
  useState,
} from 'react'
import { cn } from '@/shared/lib/cn'
import { TOUR_LAYER_ATTR } from '@/shared/lib/tour-anchors'
import { Button } from '../button/button'
import { IconButton } from '../icon-button/icon-button'
import { Spinner } from '../spinner/spinner'
import { Typewriter } from '../typewriter/typewriter'

export interface CoachAction {
  id: string
  label: string
  variant?: 'primary' | 'secondary' | 'ghost'
  tone?: 'default' | 'danger'
  onClick: () => void
  disabled?: boolean
  loading?: boolean
}

export interface CoachCardProps {
  /**
   * anchor — у прямоугольника из `anchorRef` (Radix Popper, с переворотом у краёв окна);
   * center — по центру экрана, без привязки; inline — в потоке страницы (витрина).
   */
  placement?: 'anchor' | 'center' | 'inline'
  /** Виртуальный якорь: объект с `getBoundingClientRect()`. Карточка едет за ним каждый кадр. */
  anchorRef?: RefObject<{ getBoundingClientRect(): DOMRect } | null>
  side?: 'top' | 'right' | 'bottom' | 'left'
  /** Куда выводить карточку. Для якоря внутри модального окна — узел самого окна. */
  portalContainer?: HTMLElement | null
  /** Подпись над заголовком: «Источники · Шаг 2 из 11». */
  eyebrow?: string
  title: string
  /** Текст текущей страницы; печатается как на машинке. */
  text: string
  /** Меняется на каждой странице и шаге: перезапускает печать и возвращает фокус на заголовок. */
  pageKey?: string
  /** Страница уже прочитана (вернулись «Назад») — текст сразу целиком. */
  textRead?: boolean
  pageCount?: number
  pageIndex?: number
  /** default; waiting — спиннер у счётчика (ждём прогон); error — заголовок тона Сурик. */
  tone?: 'default' | 'waiting' | 'error'
  /** До двух кнопок справа. «Назад» передаётся отдельно. */
  actions?: CoachAction[]
  /** Есть — показывается «Назад»; также `←` на клавиатуре. */
  onBack?: () => void
  /** Есть — `→` и `Enter` на заголовке работают как «Далее» (шаг-рассказ). */
  onNext?: () => void
  /** Счётчик: каждое увеличение коротко подсвечивает рамку (клик по затемнению). */
  attention?: number
  /** Подтверждение завершения обучения — внутри самой карточки. */
  confirming?: boolean
  onRequestEnd?: () => void
  onConfirmEnd?: () => void
  onCancelEnd?: () => void
  /** Дополнительное содержимое под текстом (тур его не использует). */
  children?: ReactNode
  className?: string
}

const cardClass = cn(
  'z-70 w-80 max-w-[calc(100vw-2rem)] rounded-lg border bg-surface-raised p-4 text-fg shadow-lg outline-none',
  'pointer-events-auto transition-colors duration-base ease-soft',
)

/**
 * Карточка-подсказка обучения: подпись главы и шага, заголовок, текст страницы с печатью,
 * точки страниц, кнопки по типу шага и крестик «Завершить обучение» с подтверждением внутри
 * карточки (ConfirmDialog живёт на z-50 и оказался бы под затемнением тура).
 *
 * Клавиатура: при смене шага фокус на заголовке; `Tab` — обычный порядок (своей ловушки фокуса
 * нет — она конфликтует с FocusScope модальных окон); `Esc` — подтверждение завершения (повторно —
 * «Продолжить»); `→` и `Enter` на заголовке — «Далее», `←` — «Назад».
 * Доступность: `role="dialog"`, `aria-modal="false"`, `aria-labelledby` на заголовок; весь текст
 * страницы сразу в `aria-live`, печать для скринридера скрыта.
 */
export function CoachCard({
  placement = 'anchor',
  anchorRef,
  side = 'bottom',
  portalContainer,
  eyebrow,
  title,
  text,
  pageKey,
  textRead = false,
  pageCount = 1,
  pageIndex = 0,
  tone = 'default',
  actions = [],
  onBack,
  onNext,
  attention = 0,
  confirming = false,
  onRequestEnd,
  onConfirmEnd,
  onCancelEnd,
  children,
  className,
}: CoachCardProps) {
  const headingId = useId()
  const headingRef = useRef<HTMLHeadingElement | null>(null)
  // Портал Radix монтирует содержимое со второго рендера, поэтому фокус ставим и при появлении заголовка.
  const setHeading = useCallback((node: HTMLHeadingElement | null) => {
    headingRef.current = node
    node?.focus({ preventScroll: true })
  }, [])
  const [flash, setFlash] = useState(false)

  // Фокус на заголовок при смене шага/страницы и при входе в подтверждение.
  // biome-ignore lint/correctness/useExhaustiveDependencies: pageKey и confirming — триггеры
  useEffect(() => {
    headingRef.current?.focus({ preventScroll: true })
  }, [pageKey, confirming])

  useEffect(() => {
    if (attention === 0) return
    setFlash(true)
    const timer = window.setTimeout(() => setFlash(false), 600)
    return () => window.clearTimeout(timer)
  }, [attention])

  const handleEscape = () => {
    if (confirming) onCancelEnd?.()
    else onRequestEnd?.()
  }

  const onKeyDown = (event: KeyboardEvent<HTMLElement>) => {
    if (event.key === 'Escape') {
      // Слой Radix уже обработал Esc и пометил событие — второй раз не обрабатываем.
      if (event.defaultPrevented) return
      event.preventDefault()
      event.stopPropagation()
      handleEscape()
      return
    }
    if (confirming) return
    const target = event.target as HTMLElement
    if (target.closest('input, textarea, select, [contenteditable="true"]')) return
    if (event.key === 'ArrowRight' && onNext) {
      event.preventDefault()
      onNext()
    } else if (event.key === 'ArrowLeft' && onBack) {
      event.preventDefault()
      onBack()
    } else if (event.key === 'Enter' && onNext && target === headingRef.current) {
      event.preventDefault()
      onNext()
    }
  }

  // Без слоя Radix (по центру) Esc ловим на документе — там нет DismissableLayer, который бы его забрал.
  useEffect(() => {
    if (placement !== 'center') return
    const onDocKey = (event: globalThis.KeyboardEvent) => {
      if (event.key !== 'Escape' || event.defaultPrevented) return
      event.preventDefault()
      handleEscape()
    }
    document.addEventListener('keydown', onDocKey)
    return () => document.removeEventListener('keydown', onDocKey)
  })

  const heading = confirming ? 'Завершить обучение?' : title
  const body = confirming ? 'Его можно пройти заново в меню аккаунта.' : text

  const content = (
    <>
      <div className="flex items-center gap-2">
        <div className="flex min-w-0 flex-1 items-center gap-1.5 type-caption text-fg-subtle">
          {tone === 'waiting' && !confirming && <Spinner size={14} className="text-accent" />}
          <span className="truncate" data-numeric>
            {confirming ? 'Обучение' : eyebrow}
          </span>
        </div>
        {!confirming && onRequestEnd && (
          <IconButton
            icon="x"
            label="Завершить обучение"
            size="sm"
            tooltip={false}
            onClick={onRequestEnd}
            className="-mt-1 -mr-1.5"
          />
        )}
      </div>
      <h2
        id={headingId}
        ref={setHeading}
        tabIndex={-1}
        className={cn(
          'mt-1.5 type-heading outline-none',
          tone === 'error' && !confirming ? 'text-danger-fg' : 'text-fg',
        )}
      >
        {heading}
      </h2>
      <div className="mt-1.5 type-ui text-fg-muted">
        {confirming ? (
          body
        ) : (
          <Typewriter key={pageKey} text={body} instant={textRead} className="min-h-5" />
        )}
      </div>
      {children}
      <div className="mt-4 flex items-center justify-between gap-3">
        {confirming ? (
          <>
            <Button variant="ghost" size="sm" onClick={onCancelEnd}>
              Продолжить обучение
            </Button>
            <Button variant="primary" tone="danger" size="sm" onClick={onConfirmEnd}>
              Завершить
            </Button>
          </>
        ) : (
          <>
            <div className="flex items-center gap-1.5">
              {pageCount > 1 && (
                <>
                  <ol aria-hidden="true" className="flex items-center gap-1.5">
                    {Array.from({ length: pageCount }, (_, index) => (
                      <li
                        // biome-ignore lint/suspicious/noArrayIndexKey: точки страниц неизменны по составу
                        key={index}
                        className={cn(
                          'size-1.5 rounded-full transition-colors duration-base ease-soft',
                          index === pageIndex ? 'bg-accent' : 'bg-border-strong',
                        )}
                      />
                    ))}
                  </ol>
                  <span className="sr-only">{`Страница ${pageIndex + 1} из ${pageCount}`}</span>
                </>
              )}
            </div>
            <div className="flex items-center gap-1.5">
              {onBack && (
                <Button variant="ghost" size="sm" onClick={onBack}>
                  Назад
                </Button>
              )}
              {actions.slice(0, onBack ? 2 : 3).map((action) => (
                <Button
                  key={action.id}
                  variant={action.variant ?? 'secondary'}
                  tone={action.tone}
                  size="sm"
                  disabled={action.disabled}
                  loading={action.loading}
                  onClick={action.onClick}
                >
                  {action.label}
                </Button>
              ))}
            </div>
          </>
        )}
      </div>
    </>
  )

  const frame = cn(cardClass, flash ? 'border-accent' : 'border-border', className)

  if (placement === 'inline') {
    return (
      <section
        {...{ [TOUR_LAYER_ATTR]: '' }}
        aria-labelledby={headingId}
        data-confirming={confirming || undefined}
        onKeyDown={onKeyDown}
        className={cn(frame, 'z-auto')}
      >
        {content}
      </section>
    )
  }

  if (placement === 'center') {
    return (
      <div
        {...{ [TOUR_LAYER_ATTR]: '' }}
        className="pointer-events-none fixed inset-0 z-70 grid place-items-center p-4"
      >
        <section
          role="dialog"
          aria-modal="false"
          aria-labelledby={headingId}
          onKeyDown={onKeyDown}
          className={cn(frame, 'animate-pop-in')}
        >
          {content}
        </section>
      </div>
    )
  }

  return (
    <PopoverPrimitive.Root open>
      {anchorRef && <PopoverPrimitive.Anchor virtualRef={anchorRef} />}
      <PopoverPrimitive.Portal container={portalContainer ?? undefined}>
        <PopoverPrimitive.Content
          {...{ [TOUR_LAYER_ATTR]: '' }}
          aria-modal="false"
          aria-labelledby={headingId}
          side={side}
          align="center"
          sideOffset={14}
          collisionPadding={16}
          updatePositionStrategy="always"
          onOpenAutoFocus={(event) => event.preventDefault()}
          onCloseAutoFocus={(event) => event.preventDefault()}
          onInteractOutside={(event) => event.preventDefault()}
          onEscapeKeyDown={(event) => {
            event.preventDefault()
            handleEscape()
          }}
          onKeyDown={onKeyDown}
          className={cn(frame, 'motion-pop')}
        >
          {content}
        </PopoverPrimitive.Content>
      </PopoverPrimitive.Portal>
    </PopoverPrimitive.Root>
  )
}
