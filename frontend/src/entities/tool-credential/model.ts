/**
 * Ключи инструментов (RFC-0006, шаг 1): возможности, провайдеры, приоритеты и лимиты.
 * Типы — из контракта API; здесь только подписи, порядок и статические подсказки «где взять ключ».
 */
import type { Schemas } from '@/shared/api/client'
import { formatCount, formatMoney } from '@/shared/lib/format'
import type { BadgeTone, IconName } from '@/shared/ui'

export type Credential = Schemas['Credential']
export type CredentialList = Schemas['CredentialList']
export type CapabilityCard = Schemas['CapabilityCardSchema']
export type CredentialCreate = Schemas['CredentialCreate']
export type CredentialUpdate = Schemas['CredentialUpdate']
export type CredentialCheckResult = Schemas['CredentialCheckResult']
export type CredentialKind = Credential['kinds'][number]
export type CredentialCapability = CapabilityCard['capability']
export type MonthlyLimit = Schemas['MonthlyLimit']
export type CredentialProvider = Schemas['CredentialProvider']

/** Типы задач, которые закрывает ключ. `video` — вход видео, остальные — возможности. */
export const CREDENTIAL_KIND: Record<CredentialKind, { label: string; icon: IconName }> = {
  llm: { label: 'Модели', icon: 'sparkles' },
  speech_to_text: { label: 'Распознавание речи', icon: 'transcript' },
  ocr: { label: 'Распознавание текста', icon: 'file-text' },
  vision: { label: 'Изображения', icon: 'photo' },
  video: { label: 'Видео', icon: 'video' },
  web_search: { label: 'Поиск в интернете', icon: 'search' },
  web_fetch: { label: 'Чтение страниц', icon: 'link' },
  tts: { label: 'Синтез речи', icon: 'wave-sine' },
}

/** Возможности в порядке карточек; подписи и описания приходят с сервера, это запасные. */
export const CAPABILITY: Record<
  CredentialCapability,
  { label: string; icon: IconName; description: string }
> = {
  llm: {
    label: 'Модели',
    icon: 'sparkles',
    description: 'Чтение источников, вопросы и сборка схемы.',
  },
  speech_to_text: {
    label: 'Распознавание речи',
    icon: 'transcript',
    description: 'Расшифровка голосовых заметок, аудио и видео со звуком.',
  },
  ocr: {
    label: 'Распознавание текста',
    icon: 'file-text',
    description: 'Текст со сканов PDF, которые не прочитались сами.',
  },
  vision: {
    label: 'Изображения',
    icon: 'photo',
    description: 'Описание кадров видео и изображений.',
  },
  video_understanding: {
    label: 'Разбор видео',
    icon: 'video',
    description: 'События и экраны в записи с таймкодами.',
  },
  web_search: {
    label: 'Поиск в интернете',
    icon: 'search',
    description: 'Дополнительные материалы по теме процесса.',
  },
  web_fetch: {
    label: 'Чтение страниц',
    icon: 'link',
    description: 'Текст публичной страницы по ссылке.',
  },
  tts: {
    label: 'Синтез речи',
    icon: 'wave-sine',
    description: 'Озвучка вопросов и кратких итогов.',
  },
}

/** Дата, на которую сверены подсказки «где взять ключ». */
export const PROVIDER_HINTS_DATE = '4 ноября 2026'

export interface ProviderHint {
  provider: string
  url: string
  note?: string
}

/**
 * «Где взять ключ» — статический каталог из docs/research/tool-providers-2026-11.md.
 * Полноценный каталог в коде — отдельная задача; дата указана рядом с подсказками.
 */
export const PROVIDER_HINTS: Record<CredentialCapability, ProviderHint[]> = {
  llm: [
    { provider: 'Anthropic', url: 'https://platform.claude.com/settings/keys' },
    { provider: 'OpenAI', url: 'https://platform.openai.com/settings/organization/api-keys' },
    { provider: 'OpenRouter', url: 'https://openrouter.ai/settings/keys', note: 'совместимый API' },
    { provider: 'DeepSeek', url: 'https://platform.deepseek.com/api_keys' },
    {
      provider: 'Yandex Cloud',
      url: 'https://yandex.cloud/ru/docs/iam/concepts/authorization/api-key',
      note: 'размещение в РФ',
    },
  ],
  speech_to_text: [
    { provider: 'Deepgram', url: 'https://console.deepgram.com' },
    { provider: 'OpenAI', url: 'https://platform.openai.com/settings/organization/api-keys' },
    { provider: 'Groq', url: 'https://console.groq.com/keys' },
    { provider: 'ElevenLabs', url: 'https://elevenlabs.io/app/settings/api-keys' },
    {
      provider: 'Yandex SpeechKit',
      url: 'https://yandex.cloud/ru/docs/iam/concepts/authorization/api-key',
      note: 'размещение в РФ',
    },
  ],
  ocr: [
    { provider: 'Claude', url: 'https://platform.claude.com/settings/keys' },
    { provider: 'Mistral OCR', url: 'https://console.mistral.ai/api-keys' },
    {
      provider: 'Yandex Vision OCR',
      url: 'https://yandex.cloud/ru/docs/iam/concepts/authorization/api-key',
      note: 'размещение в РФ',
    },
  ],
  vision: [
    { provider: 'Claude', url: 'https://platform.claude.com/settings/keys' },
    { provider: 'OpenAI', url: 'https://platform.openai.com/settings/organization/api-keys' },
    { provider: 'Google AI Studio', url: 'https://aistudio.google.com/apikey' },
  ],
  video_understanding: [
    { provider: 'Google AI Studio', url: 'https://aistudio.google.com/apikey' },
    { provider: 'Twelve Labs', url: 'https://playground.twelvelabs.io' },
  ],
  web_search: [
    { provider: 'Claude', url: 'https://platform.claude.com/settings/keys' },
    { provider: 'Exa', url: 'https://dashboard.exa.ai/api-keys' },
    { provider: 'Tavily', url: 'https://app.tavily.com' },
    { provider: 'Brave Search', url: 'https://api-dashboard.search.brave.com' },
  ],
  web_fetch: [
    { provider: 'Claude', url: 'https://platform.claude.com/settings/keys' },
    { provider: 'Jina Reader', url: 'https://jina.ai/reader' },
    { provider: 'Firecrawl', url: 'https://www.firecrawl.app/api-keys' },
  ],
  tts: [
    { provider: 'ElevenLabs', url: 'https://elevenlabs.io/app/settings/api-keys' },
    { provider: 'OpenAI', url: 'https://platform.openai.com/settings/organization/api-keys' },
    {
      provider: 'Yandex SpeechKit',
      url: 'https://yandex.cloud/ru/docs/iam/concepts/authorization/api-key',
      note: 'размещение в РФ',
    },
  ],
}

/** Ошибки последнего использования (RFC-0006): код → понятная подпись и тон. */
export const CREDENTIAL_ERROR: Record<string, { label: string; tone: BadgeTone }> = {
  transient: { label: 'Временный сбой', tone: 'amber' },
  quota_exhausted: { label: 'Квота исчерпана', tone: 'amber' },
  auth: { label: 'Ключ отклонён', tone: 'danger' },
  unsupported: { label: 'Не поддерживается', tone: 'neutral' },
  fatal: { label: 'Отказ провайдера', tone: 'danger' },
}

export function credentialErrorLabel(code?: string | null): string | null {
  if (!code) return null
  return CREDENTIAL_ERROR[code]?.label ?? 'Ошибка провайдера'
}

export function capabilityInfo(capability: CredentialCapability) {
  return CAPABILITY[capability]
}

export function kindLabel(kind: CredentialKind): string {
  return CREDENTIAL_KIND[kind]?.label ?? kind
}

export function providerLabel(providers: readonly CredentialProvider[], id: string): string {
  return providers.find((provider) => provider.id === id)?.label ?? id
}

/** Провайдеры, которые встречаются в карточках возможностей, без повторов. */
export function availableProviders(capabilities: readonly CapabilityCard[]): CredentialProvider[] {
  const seen = new Map<string, CredentialProvider>()
  for (const card of capabilities) {
    for (const provider of card.providers)
      if (!seen.has(provider.id)) seen.set(provider.id, provider)
  }
  return [...seen.values()].sort((a, b) => a.label.localeCompare(b.label, 'ru'))
}

/** Ключ сейчас отдыхает после исчерпанной квоты. */
export function isExhausted(credential: Credential, now: Date = new Date()): boolean {
  return Boolean(credential.exhausted_until && new Date(credential.exhausted_until) > now)
}

/** Ключ можно использовать в прогонах: включён и не отдыхает после квоты. */
export function isUsable(credential: Credential, now: Date = new Date()): boolean {
  return credential.enabled && !isExhausted(credential, now)
}

export interface MonthlyLimitPart {
  text: string
  /** Для подсказки: что именно ограничено. */
  kind: 'minutes' | 'requests' | 'cost'
}

/** Лимит на месяц: «40 минут в месяц», «120 запросов в месяц», «$5 в месяц». */
export function monthlyLimitParts(limit: MonthlyLimit | null): MonthlyLimitPart[] {
  if (!limit) return []
  const parts: MonthlyLimitPart[] = []
  if (limit.minutes != null) {
    parts.push({
      kind: 'minutes',
      text: `${formatCount(limit.minutes, ['минута', 'минуты', 'минут'])} в месяц`,
    })
  }
  if (limit.requests != null) {
    parts.push({
      kind: 'requests',
      text: `${formatCount(limit.requests, ['запрос', 'запроса', 'запросов'])} в месяц`,
    })
  }
  if (limit.cost_usd != null) {
    parts.push({ kind: 'cost', text: `${formatMoney(limit.cost_usd)} в месяц` })
  }
  return parts
}

/** Короткая подпись лимита одной строкой. */
export function monthlyLimitText(limit: MonthlyLimit | null): string | null {
  const parts = monthlyLimitParts(limit)
  return parts.length > 0 ? parts.map((part) => part.text).join(' \u00B7 ') : null
}

/** Сколько рабочих ключей закрывают возможность (считает сервер, для подписи). */
export function capabilityState(card: CapabilityCard): 'ready' | 'empty' | 'error' {
  if (card.last_error_code && card.keys === 0) return 'error'
  if (card.keys > 0) return 'ready'
  return 'empty'
}

/** Провайдеры возможности одной строкой: «Deepgram, OpenAI». */
export function providersText(providers: readonly CredentialProvider[]): string {
  return providers.map((provider) => provider.label).join(', ')
}
