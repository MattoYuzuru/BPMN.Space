/**
 * Строительные блоки витрины: раздел, образец, образец цвета, чтение токенов.
 * Витрина сама собрана по правилам дизайн-системы и проходит design-lint.
 */
import { type ReactNode, useEffect, useState } from 'react'
import { cn } from '@/shared/lib/cn'
import { contrastRatio, parseOklch, toHex } from '@/shared/lib/color'
import type { ResolvedTheme } from '@/shared/lib/theme'

export function Section({
  id,
  eyebrow,
  title,
  lead,
  children,
}: {
  id: string
  eyebrow: string
  title: string
  lead?: ReactNode
  children: ReactNode
}) {
  return (
    <section id={id} aria-labelledby={`${id}-title`} className="scroll-mt-20 py-14 first:pt-10">
      <div className="mb-8 flex max-w-2xl flex-col gap-2">
        <span className="type-code text-accent-fg">{eyebrow}</span>
        <h2 id={`${id}-title`} className="type-title text-fg">
          {title}
        </h2>
        {lead && <p className="type-body text-fg-muted">{lead}</p>}
      </div>
      <div className="@container flex flex-col gap-6">{children}</div>
    </section>
  )
}

/** Рамка образца: подпись сверху, содержимое на поверхности. */
export function Specimen({
  title,
  note,
  children,
  className,
  bodyClassName,
  canvas = false,
}: {
  title: string
  note?: ReactNode
  children: ReactNode
  className?: string
  bodyClassName?: string
  /** Фон-подложка в точку — для компонентов, которые живут поверх фона. */
  canvas?: boolean
}) {
  return (
    <figure className={cn('overflow-hidden rounded-xl border border-border bg-surface', className)}>
      <figcaption className="flex items-baseline justify-between gap-4 border-b border-border px-5 py-3">
        <span className="type-subheading text-fg">{title}</span>
        {note && <span className="type-caption text-fg-subtle">{note}</span>}
      </figcaption>
      <div
        className={cn('relative isolate p-6', canvas && 'bg-bg-subtle pattern-dots', bodyClassName)}
      >
        {children}
      </div>
    </figure>
  )
}

/** Подпись-«ярлык» над группой примеров внутри образца. */
export function Caption({ children }: { children: ReactNode }) {
  return <div className="type-caption mb-2.5 text-fg-subtle">{children}</div>
}

/** Сетка образцов, перестраивается по ширине контейнера. */
export function SpecimenGrid({ children }: { children: ReactNode }) {
  return <div className="grid gap-6 @4xl:grid-cols-2">{children}</div>
}

/** Значение CSS-переменной в заданной теме: OKLCH-строка и hex. */
export interface TokenValue {
  raw: string
  hex: string
}

/**
 * Читает значения CSS-переменных через невидимый «зонд» с нужной темой.
 * Hex считается из токенов, поэтому витрина всегда показывает то, что в tokens.css.
 */
export function useTokenValues(names: readonly string[], theme?: ResolvedTheme) {
  const [values, setValues] = useState<Record<string, TokenValue>>({})
  const key = names.join('|')
  useEffect(() => {
    const probe = document.createElement('div')
    probe.hidden = true
    if (theme) probe.setAttribute('data-theme', theme)
    document.body.append(probe)
    const style = getComputedStyle(probe)
    const next: Record<string, TokenValue> = {}
    for (const name of key.split('|')) {
      const raw = style.getPropertyValue(name).trim()
      const parsed = parseOklch(raw)
      const alpha = parsed && parsed.alpha < 1 ? ` ${Math.round(parsed.alpha * 100)}%` : ''
      next[name] = { raw, hex: parsed ? `${toHex(parsed)}${alpha}` : '' }
    }
    probe.remove()
    setValues(next)
  }, [key, theme])
  return values
}

export function ratio(fg?: TokenValue, bg?: TokenValue): number | null {
  const a = fg && parseOklch(fg.raw)
  const b = bg && parseOklch(bg.raw)
  return a && b ? contrastRatio(a, b) : null
}

/** Плашка цвета примитива палитры. */
export function PaletteChip({ cssVar, className }: { cssVar: string; className?: string }) {
  // Витрина примитивов — единственное место вне shared/ui, где цвет берётся из --palette-*.
  const swatch = { background: `var(${cssVar})` }
  return (
    <span
      aria-hidden="true"
      className={cn('block rounded-md ring-1 ring-border ring-inset', className)}
      style={swatch}
    />
  )
}
