import type { Schemas } from '@/shared/api/client'
import { formatBytes, formatClock, formatCount } from '@/shared/lib/format'
import type { IconName } from '@/shared/ui'

export type Source = Schemas['Source']
export type SourceKind = Schemas['SourceKind']
export type Quote = Schemas['Quote']
export type Sample = Schemas['Sample']
export type SampleKind = Schemas['SampleKind']

export const SOURCE_KIND: Record<SourceKind, { label: string; icon: IconName }> = {
  text: { label: 'Текст', icon: 'notes' },
  voice: { label: 'Голосовая заметка', icon: 'microphone' },
  file: { label: 'Документ', icon: 'file-description' },
  answer: { label: 'Ответ на вопрос', icon: 'message-question' },
}

/** Форматы, которые принимает бэкенд (`POST /sources/file`). */
export const ACCEPTED_FILES = ['.txt', '.md', '.csv', '.docx', '.pdf'] as const

export function isAcceptedFile(name: string): boolean {
  const lower = name.toLowerCase()
  return ACCEPTED_FILES.some((ext) => lower.endsWith(ext))
}

/** Короткая метаинформация справа в строке источника: длительность, размер или объём текста. */
export function sourceMeta(source: Source): string {
  if (source.kind === 'voice' && source.duration_sec) return formatClock(source.duration_sec)
  if (source.kind === 'file' && source.size_bytes) return formatBytes(source.size_bytes)
  return formatCount(source.content.length, ['знак', 'знака', 'знаков'])
}

export interface QuoteRange {
  start: number
  end: number
  /** Что это за цитата: повод для вопроса, доказательство решения, трассировка элемента схемы. */
  kind: 'about' | 'evidence' | 'trace'
  /** Ключ для навигации: id вопроса или элемента. */
  ref: string
}

export interface QuoteMark {
  quote: string
  kind: QuoteRange['kind']
  ref: string
}

/** Все связи фрагмента, включая перекрывающиеся цитаты разных вопросов и узлов. */
export function quoteReferences(
  content: string,
  range: Pick<QuoteRange, 'start' | 'end'>,
  marks: readonly QuoteMark[],
): QuoteMark[] {
  const refs = new Map<string, QuoteMark>()
  for (const mark of marks) {
    if (!mark.ref) continue
    const [hit] = findQuoteRanges(content, [mark])
    if (hit && hit.start < range.end && hit.end > range.start) {
      refs.set(`${mark.kind === 'trace' ? 'element' : 'question'}:${mark.ref}`, mark)
    }
  }
  return [...refs.values()]
}

/**
 * Позиции цитат в тексте источника. Цитаты из вопросов могут пересекаться; перекрытия
 * отбрасываются — побеждает более ранняя по тексту, при равном начале — доказательство.
 * Пробелы сравниваются нестрого (перенос строки в источнике и пробел в цитате совпадают).
 */
export function findQuoteRanges(content: string, marks: readonly QuoteMark[]): QuoteRange[] {
  const priority: Record<QuoteRange['kind'], number> = { evidence: 0, about: 1, trace: 2 }
  const found: QuoteRange[] = []
  for (const mark of marks) {
    const pattern = mark.quote
      .trim()
      .split(/\s+/)
      .map((part) => part.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'))
      .join('\\s+')
    if (!pattern) continue
    const match = new RegExp(pattern).exec(content)
    if (match) {
      found.push({
        start: match.index,
        end: match.index + match[0].length,
        kind: mark.kind,
        ref: mark.ref,
      })
    }
  }
  found.sort((a, b) => a.start - b.start || priority[a.kind] - priority[b.kind])
  const result: QuoteRange[] = []
  for (const range of found) {
    const last = result[result.length - 1]
    if (last && range.start < last.end) continue
    result.push(range)
  }
  return result
}

/** Разбить текст на куски: обычный текст и цитаты — для подсветки <mark>. */
export function splitByRanges(
  content: string,
  ranges: readonly QuoteRange[],
): { start: number; text: string; range?: QuoteRange }[] {
  const parts: { start: number; text: string; range?: QuoteRange }[] = []
  let cursor = 0
  for (const range of ranges) {
    if (range.start > cursor)
      parts.push({ start: cursor, text: content.slice(cursor, range.start) })
    parts.push({ start: range.start, text: content.slice(range.start, range.end), range })
    cursor = range.end
  }
  if (cursor < content.length) parts.push({ start: cursor, text: content.slice(cursor) })
  return parts
}
