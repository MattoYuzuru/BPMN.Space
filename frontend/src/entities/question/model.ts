import type { Schemas } from '@/shared/api/client'
import type { BadgeTone, IconName } from '@/shared/ui'

export type Question = Schemas['Question']
export type QuestionStatus = Schemas['QuestionStatus']
export type QuestionKind = Schemas['QuestionKind']
export type Severity = Schemas['Severity']
export type QuestionsSummary = Schemas['QuestionsSummary']

export const QUESTION_KIND: Record<QuestionKind, { label: string; icon: IconName }> = {
  missing_actor: { label: 'Не указан исполнитель', icon: 'user' },
  ambiguous_condition: { label: 'Неясное условие', icon: 'condition' },
  unclear_order: { label: 'Неясный порядок', icon: 'route' },
  missing_outcome: { label: 'Не описан исход', icon: 'flag' },
  conflict: { label: 'Источники расходятся', icon: 'conflict' },
}

export const SEVERITY: Record<Severity, { label: string; tone: BadgeTone; rank: number }> = {
  blocker: { label: 'Блокирует', tone: 'danger', rank: 0 },
  major: { label: 'Важный', tone: 'amber', rank: 1 },
  minor: { label: 'Уточнение', tone: 'neutral', rank: 2 },
}

export const QUESTION_STATUS: Record<QuestionStatus, { label: string; tone: BadgeTone }> = {
  open: { label: 'Открыт', tone: 'accent' },
  answered: { label: 'Ответ учтётся при анализе', tone: 'accent' },
  ignored: { label: 'Принято допущение', tone: 'amber' },
  resolved: { label: 'Решён', tone: 'success' },
  obsolete: { label: 'Неактуален', tone: 'neutral' },
}

/** Вкладки панели вопросов. */
export type QuestionGroup = 'open' | 'assumed' | 'resolved'

export function questionGroup(status: QuestionStatus): QuestionGroup {
  if (status === 'open' || status === 'answered') return 'open'
  if (status === 'ignored') return 'assumed'
  return 'resolved'
}

function codeNumber(code: string): number {
  const value = Number.parseInt(code.replace(/\D+/g, ''), 10)
  return Number.isNaN(value) ? Number.MAX_SAFE_INTEGER : value
}

/**
 * Порядок карточек: сначала требующие ответа (open раньше answered), затем по важности, затем по номеру.
 * В «Решено» — новые решения сверху.
 */
export function sortQuestions(questions: readonly Question[]): Question[] {
  return [...questions].sort((a, b) => {
    const groupA = questionGroup(a.status)
    if (groupA === 'resolved' && questionGroup(b.status) === 'resolved') {
      return b.updated_at.localeCompare(a.updated_at)
    }
    const waitingA = a.status === 'answered' ? 1 : 0
    const waitingB = b.status === 'answered' ? 1 : 0
    if (waitingA !== waitingB) return waitingA - waitingB
    const rank = SEVERITY[a.severity].rank - SEVERITY[b.severity].rank
    if (rank !== 0) return rank
    return codeNumber(a.code) - codeNumber(b.code)
  })
}

export function countByGroup(questions: readonly Question[]): Record<QuestionGroup, number> {
  const counts: Record<QuestionGroup, number> = { open: 0, assumed: 0, resolved: 0 }
  for (const question of questions) counts[questionGroup(question.status)] += 1
  return counts
}

/**
 * Сдвиг сводки при смене статуса вопроса — для оптимистичного обновления до ответа сервера.
 * Открытый вопрос мог считаться и «осталось», и «новый»: сначала уменьшаем «осталось».
 */
export function shiftSummary(
  summary: QuestionsSummary,
  from: QuestionStatus,
  to: QuestionStatus,
): QuestionsSummary {
  if (from === to) return summary
  const next = { ...summary }
  if (from === 'open') {
    if (next.open > 0) next.open -= 1
    else next.new = Math.max(0, next.new - 1)
  } else if (from === 'answered') next.answered = Math.max(0, next.answered - 1)
  else if (from === 'ignored') next.ignored = Math.max(0, next.ignored - 1)
  else if (from === 'resolved') next.resolved = Math.max(0, next.resolved - 1)
  if (to === 'open') next.open += 1
  else if (to === 'answered') next.answered += 1
  else if (to === 'ignored') next.ignored += 1
  else if (to === 'resolved') next.resolved += 1
  return next
}
