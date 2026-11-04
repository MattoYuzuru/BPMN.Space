import type { Schemas } from '@/shared/api/client'
import { formatBytes, formatClock, formatCount, formatNumber } from '@/shared/lib/format'
import type { BadgeTone, IconName } from '@/shared/ui'

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
  if (capability) return capabilityInfo(capability)
  if (source.kind === 'file' && isMediaFile(source.file_name)) {
    return source.media?.has_video || /\.(mp4|mov|mkv)$/i.test(source.file_name ?? '')
      ? { label: 'Видеозапись', icon: 'video' }
      : { label: 'Аудиозапись', icon: 'audio' }
  }
  return SOURCE_KIND[source.kind]
}

/** Возможность обработки (RFC-0006): что это за производный материал и чем он получен. */
export interface CapabilityInfo {
  /** Вид материала: «Расшифровка», «Распознанный текст». */
  label: string
  icon: IconName
  /** Что происходит, пока материал обрабатывается. */
  processing: string
}

/** Словарь возможностей: новый инструмент добавляется строкой, а не правкой всех подписей. */
export const CAPABILITIES: Record<string, CapabilityInfo> = {
  speech_to_text: {
    label: 'Расшифровка',
    icon: 'transcript',
    processing: 'Расшифровываю запись',
  },
  ocr: { label: 'Распознанный текст', icon: 'file-text', processing: 'Распознаю текст страниц' },
  vision: { label: 'Описание экрана', icon: 'photo', processing: 'Описываю кадры' },
  video_understanding: { label: 'Разбор видео', icon: 'video', processing: 'Смотрю видео' },
  scene_detection: { label: 'Ключевые кадры', icon: 'photo', processing: 'Выбираю кадры' },
  web_search: { label: 'Результаты поиска', icon: 'search', processing: 'Ищу в интернете' },
  web_fetch: { label: 'Страница из интернета', icon: 'link', processing: 'Читаю страницу' },
  frames: { label: 'Ключевые кадры', icon: 'photo', processing: 'Выбираю кадры' },
  media_feed: { label: 'Общая лента', icon: 'list-check', processing: 'Свожу ленту' },
  code_execution: { label: 'Результат расчёта', icon: 'file-code', processing: 'Считаю' },
  text_to_speech: { label: 'Озвучка', icon: 'wave-sine', processing: 'Озвучиваю' },
  summary: { label: 'Краткое содержание', icon: 'notes', processing: 'Сокращаю материал' },
}

const UNKNOWN_CAPABILITY: CapabilityInfo = {
  label: 'Материал от ИИ',
  icon: 'sparkles',
  processing: 'Обрабатываю материал',
}

/** Незнакомая возможность не показывается сырым `snake_case`: у неё спокойная общая подпись. */
export function capabilityInfo(capability: string | null | undefined): CapabilityInfo {
  return (capability && CAPABILITIES[capability]) || UNKNOWN_CAPABILITY
}

export function capabilityLabel(capability: string | null | undefined): string {
  return capabilityInfo(capability).label
}

/** Подпись, короткая метка, пояснение и тон бейджа для уровня доверия. */
export interface SourceTrustInfo {
  label: string
  short: string
  description: string
  tone: BadgeTone
}

/** Уровни доверия (RFC-0006): что из материала можно цитировать в основаниях схемы. */
export const SOURCE_TRUST: Record<SourceTrust, SourceTrustInfo> = {
  primary: {
    label: 'Первоисточник',
    short: 'первоисточник',
    description: 'Текст пользователя: годится в основания схемы.',
    tone: 'neutral',
  },
  extracted: {
    label: 'Извлечено ИИ',
    short: 'извлечено',
    description: 'Расшифровка, OCR или текст страницы: машинное, но сверяемое с исходником.',
    tone: 'neutral',
  },
  observed: {
    label: 'Наблюдение',
    short: 'по кадрам',
    description: 'Описание кадров или событий видео: цитата идёт с пометкой «по изображению».',
    tone: 'neutral',
  },
  external: {
    label: 'Внешний источник',
    short: 'внешний',
    description: 'Результат поиска или публичная страница: ниже приоритетом при конфликте.',
    tone: 'neutral',
  },
  agent: {
    label: 'От агента',
    short: 'от агента',
    description: 'Материал внешнего агента: видно, кто и каким токеном его добавил.',
    tone: 'accent',
  },
  summary: {
    label: 'Краткое содержание',
    short: 'пересказ',
    description: 'Только навигация: в контекст модели и в основания схемы не идёт.',
    tone: 'amber',
  },
}

const UNKNOWN_TRUST: SourceTrustInfo = {
  label: 'Уровень доверия неизвестен',
  short: 'без уровня',
  description: 'Сервер прислал уровень доверия, которого эта версия интерфейса ещё не знает.',
  tone: 'neutral',
}

/** Известный уровень доверия или null: по нему дерево решает, показывать ли метку. */
export function knownSourceTrust(trust: string): SourceTrustInfo | null {
  return (SOURCE_TRUST as Record<string, SourceTrustInfo>)[trust] ?? null
}

/** Подпись уровня доверия; незнакомый уровень не выдаётся за первоисточник. */
export function sourceTrustInfo(trust: string): SourceTrustInfo {
  return knownSourceTrust(trust) ?? UNKNOWN_TRUST
}

/** Материал принёс внешний агент (RFC-0007): у узла своя метка в дереве. */
export function isAgentSource(source: Source): boolean {
  return source.origin === 'agent'
}

/** Стоимость обработки, если провайдер её сообщил (RFC-0006). */
export function derivationCost(source: Source): number | null {
  return source.derivation?.cost_usd ?? null
}

const PAGE_FORMS = ['страница', 'страницы', 'страниц'] as const

/** Короткая подпись для строки дерева: «2 страницы без текста». */
export function unreadablePagesLabel(pages: readonly number[] | null | undefined): string | null {
  if (!pages || pages.length === 0) return null
  return `${formatCount(pages.length, PAGE_FORMS)} без текста`
}

/** Подробность для листа источника: какие именно страницы PDF остались без текстового слоя. */
export function unreadablePagesText(pages: readonly number[] | null | undefined): string | null {
  if (!pages || pages.length === 0) return null
  const shown = pages
    .slice(0, 8)
    .map((page) => formatNumber(page))
    .join(', ')
  const rest = pages.length > 8 ? ` и ещё ${formatCount(pages.length - 8, PAGE_FORMS)}` : ''
  return `Не прочитан текст страниц: ${shown}${rest}. Это сканы без текстового слоя.`
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

/** Сколько всего узлов в дереве материалов: исходные и все производные, любой глубины. */
export function countSourceTree(nodes: readonly SourceNode[]): number {
  return nodes.reduce((total, node) => total + 1 + countSourceTree(node.children), 0)
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

/** Время из таймкода `[мм:сс]` или `[ч:мм:сс]` — в секунды; не таймкод — null. */
export function parseTimecode(text: string): number | null {
  const match = /^(\d{1,2}):(\d{2})(?::(\d{2}))?$/.exec(text.trim().replace(/^\[|\]$/g, ''))
  if (!match) return null
  const first = Number(match[1])
  const second = Number(match[2])
  const third = match[3] === undefined ? null : Number(match[3])
  if (second >= 60 || (third !== null && third >= 60)) return null
  return third === null ? first * 60 + second : first * 3600 + second * 60 + third
}

/** Исходная запись для плеера: сама запись или корень дерева, у которого есть медиа. */
export function mediaRootSource(sources: readonly Source[], source: Source): Source | null {
  if (source.media) return source
  let current: Source | undefined = source
  const seen = new Set<string>([source.id])
  while (current?.parent_id) {
    if (seen.has(current.parent_id)) return null
    seen.add(current.parent_id)
    current = sources.find((item) => item.id === current?.parent_id)
    if (current?.media) return current
  }
  return null
}

export interface SourcePlayback {
  /** Запись, чей файл играет плеер. */
  mediaSource: Source
  /** Источник, у которого спрашиваем реплики (`/segments` умеет и запись, и расшифровку). */
  segmentsSourceId: string
  hasVideo: boolean
}

/**
 * Что играть в листе источника: саму запись или корень дерева для расшифровки и производных.
 * У расшифровки реплики берём у неё, у остальных производных — у записи.
 */
export function sourcePlayback(sources: readonly Source[], source: Source): SourcePlayback | null {
  const mediaSource = mediaRootSource(sources, source)
  if (!mediaSource) return null
  const isTranscript = source.derivation?.capability === 'speech_to_text'
  return {
    mediaSource,
    segmentsSourceId: isTranscript ? source.id : mediaSource.id,
    hasVideo: Boolean(mediaSource.media?.has_video),
  }
}

const DERIVATION_EXTRA: Record<string, (params: Record<string, unknown>) => string | null> = {
  frames: (params) =>
    typeof params.frames === 'number'
      ? `${formatCount(params.frames, ['кадр', 'кадра', 'кадров'])}`
      : null,
  media_feed: (params) => {
    const total = typeof params.total_frames === 'number' ? params.total_frames : null
    return total ? `${formatCount(total, ['кадр', 'кадра', 'кадров'])} в ленте` : null
  },
  summary: () => 'Навигация, не основание схемы',
}

/** Дополнительные факты производного узла: кадры, страницы, навигация по сводке. */
export function derivationDetails(source: Source): string[] {
  const derivation = source.derivation
  if (!derivation) return []
  const details: string[] = []
  const extra = DERIVATION_EXTRA[derivation.capability]?.(derivation.params ?? {})
  if (extra) details.push(extra)
  const remaining = remainingOcrPages(source)
  if (remaining.length > 0) {
    details.push(`не распознано ${formatCount(remaining.length, PAGE_FORMS)}`)
  }
  return details
}

const remainingOcrPagesCache = new WeakMap<Source, number[]>()

/** Те же правила, что в `media.ts`, без циклического импорта: страницы из params. */
export function remainingOcrPages(source: Source): number[] {
  const cached = remainingOcrPagesCache.get(source)
  if (cached) return cached
  const raw = source.derivation?.params?.pages_remaining
  const pages = Array.isArray(raw)
    ? raw.filter((page): page is number => typeof page === 'number')
    : []
  remainingOcrPagesCache.set(source, pages)
  return pages
}

/** Пояснение к уровню доверия для листа источника. */
export function trustNotice(trust: SourceTrust): string | null {
  if (trust === 'summary') return 'Навигация по записи: цитаты из сводки не идут в основания схемы.'
  if (trust === 'observed') return 'Получено по изображению и таймкодам записи.'
  return null
}
