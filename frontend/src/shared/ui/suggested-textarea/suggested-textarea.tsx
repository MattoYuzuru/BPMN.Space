import { useEffect, useState } from 'react'
import { useTypewriter } from '@/shared/hooks/use-typewriter'
import { Button } from '../button/button'
import { Textarea, type TextareaProps } from '../textarea/textarea'

/** Сколько символов подсказки видно «призраком» в пустом поле. */
export const SUGGESTION_PREVIEW_CHARS = 140

/** Скорость «печати» подсказки в поле, символов в секунду. */
const INSERT_CPS = 120

export interface SuggestedTextareaProps
  extends Omit<TextareaProps, 'value' | 'onChange' | 'defaultValue'> {
  value: string
  onValueChange: (value: string) => void
  /** Текст-подсказка; пока поле пустое, он виден приглушённым цветом. Нет подсказки — обычное поле. */
  suggestion?: string | null
  /** «Вставить»: подсказка начала впечатываться в поле. */
  onInsert?: (suggestion: string) => void
  /** Подсказка закрыта: «Напишу сам» или первый собственный ввод. */
  onDismiss?: () => void
}

/** Начало текста для «призрака»: до 140 символов по границе слова и многоточие. */
export function suggestionPreview(text: string): string {
  if (text.length <= SUGGESTION_PREVIEW_CHARS) return text
  const cut = text.slice(0, SUGGESTION_PREVIEW_CHARS)
  const space = cut.lastIndexOf(' ')
  return `${(space > SUGGESTION_PREVIEW_CHARS * 0.6 ? cut.slice(0, space) : cut).trimEnd()}…`
}

type Phase = 'offer' | 'typing' | 'closed'

/**
 * Поле с подсказкой-автодополнением. В пустом поле виден приглушённый «призрак» начала подсказки,
 * под полем — «Вставить» и «Напишу сам». «Вставить» (или Tab в пустом поле) впечатывает текст в
 * поле, как будто его пишет сам человек; нажатие клавиши во время печати допечатывает остаток
 * сразу и отдаёт управление. Любой собственный ввод закрывает подсказку. `prefers-reduced-motion`
 * — текст вставляется целиком.
 */
export function SuggestedTextarea({
  value,
  onValueChange,
  suggestion,
  onInsert,
  onDismiss,
  placeholder,
  onKeyDown,
  onPaste,
  ...props
}: SuggestedTextareaProps) {
  const text = suggestion ?? ''
  const [phase, setPhase] = useState<Phase>('offer')
  const typed = useTypewriter({
    text,
    cps: INSERT_CPS,
    punctuationPause: false,
    active: phase === 'typing' && text.length > 0,
    onComplete: () => setPhase('closed'),
  })

  // Напечатанная часть едет в поле, пока идёт печать.
  const { text: typedText } = typed
  useEffect(() => {
    if (phase === 'typing') onValueChange(typedText)
  }, [phase, typedText, onValueChange])

  const offered = text.length > 0 && phase === 'offer' && value === ''
  const insert = () => {
    if (!offered) return
    setPhase('typing')
    onInsert?.(text)
  }
  const dismiss = () => {
    setPhase('closed')
    onDismiss?.()
  }

  return (
    <div className="flex flex-col gap-2">
      <Textarea
        {...props}
        value={value}
        placeholder={offered ? suggestionPreview(text) : placeholder}
        data-suggested={offered || undefined}
        onChange={(event) => {
          if (phase === 'typing') return
          if (phase === 'offer' && text) {
            setPhase('closed')
            onDismiss?.()
          }
          onValueChange(event.target.value)
        }}
        onKeyDown={(event) => {
          onKeyDown?.(event)
          if (event.defaultPrevented) return
          if (phase === 'typing') {
            // Любая клавиша во время печати: допечатать остаток и отдать управление.
            if (!event.metaKey && !event.ctrlKey && event.key !== 'Tab') event.preventDefault()
            typed.finish()
            return
          }
          if (offered && event.key === 'Tab' && !event.shiftKey) {
            event.preventDefault()
            insert()
          }
        }}
        onPaste={(event) => {
          onPaste?.(event)
          if (phase === 'typing') {
            event.preventDefault()
            typed.finish()
          }
        }}
      />
      {offered && (
        <div className="flex items-center gap-2 animate-fade-in">
          <Button size="sm" variant="primary" leadingIcon="sparkles" onClick={insert}>
            Вставить
          </Button>
          <Button size="sm" variant="ghost" onClick={dismiss}>
            Напишу сам
          </Button>
        </div>
      )}
    </div>
  )
}
