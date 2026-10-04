import { useReducedMotion } from 'motion/react'
import { useCallback, useEffect, useRef, useState } from 'react'

/** Шаг таймера печати, мс. */
const TICK_MS = 30
const LONG_PAUSE = new Set(['.', '!', '?', '…'])
const SHORT_PAUSE = new Set([',', ';', ':', '\u2014', '\u2013'])

/**
 * Моменты (мс от старта), когда на экране становится 1, 2, … символов. Знаки препинания
 * добавляют паузу после себя: точка, вопрос, восклицание, многоточие — 120 мс, запятая,
 * двоеточие, тире — 60 мс. Случайных «опечаток» нет. `maxMs` ограничивает общую длительность.
 */
export function typingTimes(
  text: string,
  cps: number,
  punctuationPause: boolean,
  maxMs?: number,
): number[] {
  const step = 1000 / cps
  const times: number[] = []
  let now = 0
  for (const char of text) {
    now += step
    times.push(now)
    if (punctuationPause) {
      if (LONG_PAUSE.has(char)) now += 120
      else if (SHORT_PAUSE.has(char)) now += 60
    }
  }
  // Длинную страницу слегка ускоряем, чтобы целиком она печаталась не дольше maxMs.
  const total = times.at(-1) ?? 0
  if (maxMs !== undefined && total > maxMs) return times.map((time) => (time * maxMs) / total)
  return times
}

export interface UseTypewriterOptions {
  text: string
  /** Символов в секунду: ~45 для текста карточки, ~120 для «печати» в поле ввода. */
  cps?: number
  /** Верхняя граница длительности печати всего текста, мс (текст карточки — 3500). */
  maxMs?: number
  /** Паузы на знаках препинания. Для поля ввода обычно выключают. */
  punctuationPause?: boolean
  /** false — печать не началась, текст пуст (запускается позже: «Вставить»). */
  active?: boolean
  /** Показать сразу целиком (уже прочитанная страница). */
  instant?: boolean
  /** Вызывается один раз, когда текст показан целиком (в том числе после `finish`). */
  onComplete?: () => void
}

export interface TypewriterState {
  /** Напечатанная часть. */
  text: string
  /** Весь текст показан. */
  done: boolean
  /** Мгновенно допечатать. */
  finish: () => void
}

/**
 * Эффект печати для текста карточки и для заполнения поля ввода (`cps: 120`,
 * `punctuationPause: false`). `prefers-reduced-motion` — текст сразу целиком.
 * Смена `text` запускает печать заново.
 */
export function useTypewriter({
  text,
  cps = 45,
  punctuationPause = true,
  maxMs,
  active = true,
  instant = false,
  onComplete,
}: UseTypewriterOptions): TypewriterState {
  const reduced = useReducedMotion()
  const immediate = instant || Boolean(reduced)
  const [progress, setProgress] = useState({ text, count: 0 })
  const count = progress.text === text ? progress.count : 0
  const shown = !active ? 0 : immediate ? text.length : count
  const done = active && text.length > 0 && shown >= text.length

  useEffect(() => {
    if (!active || immediate || done || text.length === 0) return
    const times = typingTimes(text, cps, punctuationPause, maxMs)
    let elapsed = 0
    let timer = 0
    const tick = () => {
      elapsed += TICK_MS
      let visible = 0
      while (visible < times.length && (times[visible] as number) <= elapsed) visible += 1
      setProgress((prev) => ({
        text,
        count: Math.max(prev.text === text ? prev.count : 0, visible),
      }))
      timer = window.setTimeout(tick, TICK_MS)
    }
    timer = window.setTimeout(tick, TICK_MS)
    return () => window.clearTimeout(timer)
  }, [text, cps, punctuationPause, maxMs, active, immediate, done])

  const onCompleteRef = useRef(onComplete)
  onCompleteRef.current = onComplete
  useEffect(() => {
    if (done) onCompleteRef.current?.()
  }, [done])

  const finish = useCallback(() => setProgress({ text, count: text.length }), [text])

  return { text: text.slice(0, shown), done, finish }
}
