import { useEffect, useRef, useState } from 'react'
import type { Question, QuestionStatus } from '@/entities/question'

/** Сколько решённый вопрос остаётся во вкладке «Открытые», показывая доказательство. */
export const SETTLE_MS = 2200
/** Сколько новый вопрос помечен как «Новый». */
export const FRESH_MS = 60_000

export interface Transitions {
  /** Только что решённые: ещё видны среди открытых. */
  settling: ReadonlySet<string>
  /** Появившиеся после открытия экрана. */
  fresh: ReadonlySet<string>
}

/**
 * Следит за сменой статусов вопросов (SSE, ответ сервера, перезапрос) и отмечает переходы,
 * которые стоит показать движением: open/answered -> resolved и появление нового вопроса.
 * Первая загрузка ничего не отмечает.
 */
export function detectTransitions(
  previous: ReadonlyMap<string, QuestionStatus> | null,
  questions: readonly Question[],
): { resolved: string[]; added: string[] } {
  if (!previous) return { resolved: [], added: [] }
  const resolved: string[] = []
  const added: string[] = []
  for (const question of questions) {
    const before = previous.get(question.id)
    if (before === undefined) {
      if (question.status === 'open') added.push(question.id)
    } else if (
      question.status === 'resolved' &&
      (before === 'open' || before === 'answered' || before === 'ignored')
    ) {
      resolved.push(question.id)
    }
  }
  return { resolved, added }
}

export function useQuestionTransitions(questions: readonly Question[]): Transitions {
  const previous = useRef<Map<string, QuestionStatus> | null>(null)
  const [settling, setSettling] = useState<ReadonlySet<string>>(new Set())
  const [fresh, setFresh] = useState<ReadonlySet<string>>(new Set())
  const timers = useRef<ReturnType<typeof setTimeout>[]>([])

  useEffect(() => {
    const { resolved, added } = detectTransitions(previous.current, questions)
    previous.current = new Map(questions.map((question) => [question.id, question.status]))
    const schedule = (ids: string[], setter: typeof setSettling, ms: number) => {
      if (ids.length === 0) return
      setter((current) => new Set([...current, ...ids]))
      timers.current.push(
        setTimeout(() => {
          setter((current) => new Set([...current].filter((id) => !ids.includes(id))))
        }, ms),
      )
    }
    schedule(resolved, setSettling, SETTLE_MS)
    schedule(added, setFresh, FRESH_MS)
  }, [questions])

  useEffect(() => () => timers.current.forEach(clearTimeout), [])
  return { settling, fresh }
}
