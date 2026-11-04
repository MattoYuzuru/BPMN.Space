import type { Schemas } from '@/shared/api/client'
import { formatBytes, formatClock, formatCount } from '@/shared/lib/format'
import type { IconName } from '@/shared/ui'

export type Source = Schemas['Source']
export type SourceKind = Schemas['SourceKind']
export type SourceOrigin = Schemas['SourceOrigin']
export type SourceTrust = Schemas['SourceTrust']
export type Quote = Schemas['Quote']
export type Sample = Schemas['Sample']
export type SampleKind = Schemas['SampleKind']

export const SOURCE_KIND: Record<SourceKind, { label: string; icon: IconName }> = {
  text: { label: 'Текст', icon: 'notes' },
  voice: { label: 'Голосовая заметка', icon: 'microphone' },
  file: { label: 'Документ', icon: 'file-description' },
  answer: { label: 'Ответ на вопрос', icon: 'message-question' },
}

/** Форматы, которые принимает бэкенд (`POST /sources/file`): документы и записи. */
export const DOCUMENT_FILES = ['.txt', '.md', '.csv', '.docx', '.xlsx', '.pptx', '.pdf'] as const
export const MEDIA_FILES = [
  '.mp3',
  '.wav',
  '.ogg',
  '.opus',
  '.m4a',
  '.flac',
  '.aac',
  '.webm',
  '.mp4',
  '.mov',
  '.mkv',
] as const
export const ACCEPTED_FILES = [...DOCUMENT_FILES, ...MEDIA_FILES] as const

/** Подсказка в зонах загрузки: документы и записи, без полного перечня аудио-расширений. */
export const ACCEPTED_FILES_HINT = '.txt, .md, .csv, .docx, .xlsx, .pptx, .pdf, аудио и видео'

export function isAcceptedFile(name: string): boolean {
  const lower = name.toLowerCase()
  return ACCEPTED_FILES.some((ext) => lower.endsWith(ext))
}

/** Короткая метаинформация справа в строке источника: длительность, размер или объём текста. */
export function sourceMeta(source: Source): string {
  if (source.duration_sec && source.kind !== 'text' && source.kind !== 'answer')
    return formatClock(source.duration_sec)
  if (source.kind === 'file' && source.size_bytes) return formatBytes(source.size_bytes)
  return formatCount(source.content.length, ['знак', 'знака', 'знаков'])
}

export function isMediaFile(name?: string | null): boolean {
  const lower = (name ?? '').toLowerCase()
  return MEDIA_FILES.some((ext) => lower.endsWith(ext))
}

/** Производный узел дерева: получен сервером из исходного файла (RFC-0006), метка «ИИ». */
export function isDerived(source: Source): boolean {
  return source.origin === 'derived'
}

/** Подпись и иконка вида источника; запись отличается от документа, расшифровка — от текста. */
export function sourceKindOf(source: Source): { label: string; icon: IconName } {
  const capability = source.derivation?.capability
  if (capability && CAPABILITY[capability]) return CAPABILITY[capability]
  if (source.kind === 'file' && isMediaFile(source.file_name)) {
    return source.media?.has_video || /\.(mp4|mov|mkv)$/i.test(source.file_name ?? '')
      ? { label: 'Видеозапись', icon: 'video' }
      : { label: 'Аудиозапись', icon: 'audio' }
  }
  return SOURCE_KIND[source.kind]
}

const CAPABILITY: Record<string, { label: string; icon: IconName }> = {
  speech_to_text: { label: 'Расшифровка', icon: 'transcript' },
}

const PROVIDER: Record<string, string> = {
  deepgram: 'Deepgram',
  mock: 'Демо-распознавание',
}

/** Кто получил производный узел: «Deepgram, nova-3». Пусто для исходных материалов. */
export function derivationLabel(source: Source): string | undefined {
  const derivation = source.derivation
  if (!derivation) return undefined
  const provider = PROVIDER[derivation.provider] ?? derivation.provider
  return derivation.model ? `${provider}, ${derivation.model}` : provider
}

export interface SourceNode {
  source: Source
  children: SourceNode[]
}

/**
 * Дерево материалов по `parent_id`: исходные файлы и вложенные производные узлы.
 * Порядок — как в списке (по `created_at`); узел без найденного родителя становится корнем.
 */
export function buildSourceTree(sources: readonly Source[]): SourceNode[] {
  const nodes = new Map(
    sources.map((source) => [source.id, { source, children: [] as SourceNode[] }]),
  )
  const roots: SourceNode[] = []
  for (const node of nodes.values()) {
    const parent = node.source.parent_id ? nodes.get(node.source.parent_id) : undefined
    if (parent && parent !== node) parent.children.push(node)
    else roots.push(node)
  }
  return roots
}

/**
 * Разбить текст расшифровки по таймкодам `[мм:сс]` (и `[ч:мм:сс]`): нечётные элементы — таймкоды.
 * Только для показа; цитаты и поиск по тексту работают с исходной строкой.
 */
export function splitTimecodes(text: string): string[] {
  return text.split(/(\[\d{1,3}(?::\d{2}){1,2}\])/)
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

/** Сколько знаков источника показывать сразу: длинные документы выводятся порциями. */
export const DISPLAY_CHUNK_CHARS = 120_000

/**
 * Часть кусков текста, помещающаяся в `limit` знаков (только для показа, источник не меняется).
 * Кусок, пересекающий границу, обрезается; цитата целиком остаётся в одном куске-<mark>.
 */
export function limitParts<T extends { start: number; text: string; range?: QuoteRange }>(
  parts: readonly T[],
  limit: number,
): T[] {
  const visible: T[] = []
  for (const part of parts) {
    if (part.start >= limit) break
    const room = limit - part.start
    visible.push(
      !part.range && part.text.length > room ? { ...part, text: part.text.slice(0, room) } : part,
    )
  }
  return visible
}

/** id всех потомков источника по `parent_id` (дети, внуки…), без самого источника. */
export function descendantIds(sources: readonly Source[], rootId: string): Set<string> {
  const found = new Set<string>()
  let frontier = [rootId]
  while (frontier.length > 0) {
    const next = sources
      .filter((source) => source.parent_id && frontier.includes(source.parent_id))
      .map((source) => source.id)
      .filter((id) => id !== rootId && !found.has(id))
    for (const id of next) found.add(id)
    frontier = next
  }
  return found
}
