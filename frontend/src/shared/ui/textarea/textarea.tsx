import { type ComponentProps, useCallback, useLayoutEffect, useRef } from 'react'
import { cn } from '@/shared/lib/cn'
import { mergeRefs } from '@/shared/lib/merge-refs'
import { useFieldControl } from '../field/field'

export interface TextareaProps extends ComponentProps<'textarea'> {
  invalid?: boolean
  /** Высота подстраивается под текст между minRows и maxRows, дальше появляется прокрутка. */
  minRows?: number
  maxRows?: number
}

/** Многострочное поле с авто-ростом. Для ответов на вопросы, текстовых источников, заметок. */
export function Textarea({
  invalid,
  disabled,
  id,
  minRows = 3,
  maxRows = 12,
  className,
  ref,
  onInput,
  value,
  'aria-describedby': describedBy,
  ...props
}: TextareaProps) {
  const innerRef = useRef<HTMLTextAreaElement>(null)
  const field = useFieldControl({ id, invalid, disabled, describedBy })

  const resize = useCallback(() => {
    const el = innerRef.current
    if (!el) return
    const style = window.getComputedStyle(el)
    const lineHeight = Number.parseFloat(style.lineHeight) || 20
    const chrome =
      Number.parseFloat(style.paddingTop) +
      Number.parseFloat(style.paddingBottom) +
      Number.parseFloat(style.borderTopWidth) +
      Number.parseFloat(style.borderBottomWidth)
    const min = lineHeight * minRows + chrome
    const max = lineHeight * maxRows + chrome
    el.style.height = 'auto'
    const content = el.scrollHeight + Number.parseFloat(style.borderTopWidth) * 2
    el.style.height = `${Math.min(Math.max(content, min), max)}px`
    el.style.overflowY = content > max ? 'auto' : 'hidden'
  }, [minRows, maxRows])

  // Пересчитываем высоту и при внешнем изменении value (очистка после отправки).
  // biome-ignore lint/correctness/useExhaustiveDependencies: value — триггер пересчёта
  useLayoutEffect(() => {
    resize()
  }, [resize, value])

  return (
    <textarea
      ref={mergeRefs(innerRef, ref)}
      id={field.id}
      value={value}
      disabled={field.disabled}
      aria-invalid={field['aria-invalid']}
      aria-describedby={field['aria-describedby']}
      rows={minRows}
      onInput={(event) => {
        resize()
        onInput?.(event)
      }}
      className={cn(
        'block w-full resize-none rounded-md border border-border bg-surface px-2.5 py-1.5 text-sm text-fg shadow-xs outline-none',
        'transition-[border-color,box-shadow,background-color] duration-(--duration-base) ease-soft',
        'placeholder:text-fg-subtle hover:border-border-strong',
        'focus:border-accent focus:ring-3 focus:ring-accent/15 focus:hover:border-accent',
        'aria-invalid:border-danger aria-invalid:focus:ring-danger/15',
        'disabled:cursor-not-allowed disabled:bg-bg-subtle disabled:opacity-60',
        className,
      )}
      {...props}
    />
  )
}
