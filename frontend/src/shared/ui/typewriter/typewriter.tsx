import { useEffect } from 'react'
import { useTypewriter } from '@/shared/hooks/use-typewriter'
import { cn } from '@/shared/lib/cn'

export interface TypewriterProps {
  text: string
  /** Символов в секунду. */
  cps?: number
  /** Показать сразу целиком: страница уже прочитана. */
  instant?: boolean
  /** Клик по тексту и любая клавиша (кроме Tab) допечатывают его. По умолчанию включено. */
  skippable?: boolean
  /** Свой регион `aria-live` с полным текстом. false — объявлением занимается родитель (карточка). */
  live?: boolean
  onDone?: () => void
  className?: string
}

/**
 * Текст, который печатается как на машинке (~45 символов/с, паузы на знаках препинания).
 * Место под текст занято сразу — ненапечатанная часть лежит в потоке невидимой, поэтому высота
 * и переносы не прыгают. Скринридер получает весь текст сразу через `aria-live`, печать для него
 * скрыта. `prefers-reduced-motion` — текст сразу целиком.
 */
export function Typewriter({
  text,
  cps = 45,
  instant = false,
  skippable = true,
  live = true,
  onDone,
  className,
}: TypewriterProps) {
  const typed = useTypewriter({ text, cps, instant, maxMs: 3500, onComplete: onDone })
  const { done, finish } = typed

  useEffect(() => {
    if (!skippable || done) return
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Tab' || event.key === 'Shift' || event.metaKey || event.ctrlKey) return
      finish()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [skippable, done, finish])

  return (
    // biome-ignore lint/a11y/noStaticElementInteractions: клик — дополнительный способ допечатать, клавиатурный путь — любая клавиша
    // biome-ignore lint/a11y/useKeyWithClickEvents: клавиатурный путь — глобальный keydown выше
    <span
      className={cn('block', !done && skippable && 'cursor-pointer', className)}
      onClick={skippable && !done ? finish : undefined}
    >
      {live && (
        <span aria-live="polite" className="sr-only">
          {text}
        </span>
      )}
      <span aria-hidden="true">
        {typed.text}
        <span className="invisible">{text.slice(typed.text.length)}</span>
      </span>
    </span>
  )
}
