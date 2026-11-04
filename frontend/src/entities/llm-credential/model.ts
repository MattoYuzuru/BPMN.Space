import type { Schemas } from '@/shared/api/client'
import { formatDate, formatNumber } from '@/shared/lib/format'

export type LlmCredential = Schemas['LlmCredential']
export type LlmProvider = LlmCredential['provider']
export type LlmModel = Schemas['LlmModel']
export type ModelCapabilities = Schemas['LlmModelCapabilities']
export type Effort = NonNullable<Schemas['RunProfile']['effort']>

/** Уровни глубины работы модели (RFC-0005) в порядке «дешевле → тщательнее». */
export const EFFORTS: { value: Effort; label: string }[] = [
  { value: 'low', label: 'Быстро' },
  { value: 'medium', label: 'Обычно' },
  { value: 'high', label: 'Тщательно' },
  { value: 'xhigh', label: 'Очень тщательно' },
  { value: 'max', label: 'Максимум' },
]

export function isEffort(value: unknown): value is Effort {
  return EFFORTS.some((item) => item.value === value)
}

/** Уровни, которые принимает модель; «Очень тщательно» — только если модель его умеет. */
export function effortOptions(caps: ModelCapabilities | undefined): typeof EFFORTS {
  const levels = new Set(caps?.effort_levels ?? [])
  return EFFORTS.filter((item) => levels.has(item.value))
}

/** Уровень, с которым пойдёт запуск: выбранный, если модель его умеет, иначе умолчание модели. */
export function effectiveEffort(
  effort: Effort | undefined,
  caps: ModelCapabilities | undefined,
): Effort | null {
  const levels = caps?.effort_levels ?? []
  if (levels.length === 0) return null
  if (effort && levels.includes(effort)) return effort
  return caps?.effort_default ?? null
}

export function effortLabel(effort: Effort): string {
  return EFFORTS.find((item) => item.value === effort)?.label ?? effort
}

/** Возможности модели одной строкой: окно, ответ, вложения, цены с датой. */
export function capabilitySummary(caps: ModelCapabilities): string[] {
  const parts: string[] = []
  if (caps.context_tokens) parts.push(`окно ${tokens(caps.context_tokens)}`)
  if (caps.max_output_tokens) parts.push(`ответ до ${tokens(caps.max_output_tokens)}`)
  if (caps.vision && caps.pdf_input) parts.push('изображения и PDF')
  else if (caps.vision) parts.push('изображения')
  const options = effortOptions(caps)
  if (options.length > 0) {
    const first = options[0]?.label.toLowerCase()
    const last = options[options.length - 1]?.label.toLowerCase()
    parts.push(options.length > 1 ? `уровни от «${first}» до «${last}»` : `уровень «${first}»`)
  }
  if (caps.prices) {
    const { input, output, checked_on } = caps.prices
    parts.push(
      `$${price(input)} / $${price(output)} за 1 млн токенов, цены на ${formatDate(new Date(checked_on))}`,
    )
  }
  if (!caps.known && parts.length === 0) parts.push('возможности модели неизвестны')
  return parts
}

function tokens(value: number): string {
  if (value >= 1_000_000 && value % 1_000_000 === 0) {
    return `${formatNumber(value / 1_000_000)}\u00A0млн токенов`
  }
  if (value >= 1000) return `${formatNumber(Math.round(value / 1000))}\u00A0тыс. токенов`
  return `${formatNumber(value)} токенов`
}

function price(value: number): string {
  return value.toLocaleString('ru-RU', { maximumFractionDigits: 3 })
}

export const PROVIDERS: { value: LlmProvider; label: string }[] = [
  { value: 'anthropic', label: 'Anthropic' },
  { value: 'openai', label: 'OpenAI' },
  { value: 'openai_compatible', label: 'Совместимый с OpenAI' },
]

/** Разделитель в подписях («модель · ключ») и точки маски ключа; символы заданы кодами. */
export const LABEL_SEPARATOR = ' \u00B7 '
const MASK = '\u2022\u2022\u2022\u2022'

export const SERVER_MODEL_LABEL = 'Сервер по умолчанию'

export function providerLabel(provider: LlmProvider): string {
  return PROVIDERS.find((item) => item.value === provider)?.label ?? provider
}

/** `claude-opus-5-5` → «Claude Opus 5.5»; остальные идентификаторы остаются как есть. */
export function modelLabel(id: string): string {
  const claude = /^claude-(opus|sonnet|haiku|fable)-(\d+)-(\d+)$/.exec(id)
  if (!claude) return id
  const [, family = '', major, minor] = claude
  return `Claude ${family.charAt(0).toUpperCase()}${family.slice(1)} ${major}.${minor}`
}

/** Подсказка ключа для списка: маска и последние 4 символа; у коротких ключей только маска. */
export function keyMask(hint: string): string {
  return `${MASK}${hint}`
}

/** Явный выбор для запуска: ключ, модель и уровень. Не выбрано — ключ по умолчанию, затем сервер. */
export interface ModelChoice {
  credentialId: string
  model: string
  /** Глубина работы; не задана — умолчание модели на сервере. */
  effort?: Effort
}

export interface ResolvedChoice {
  credential: LlmCredential
  model: string
  effort?: Effort
}

/** Что реально будет использовано: явный выбор, иначе ключ по умолчанию; `null` — сервер. */
export function resolveChoice(
  credentials: LlmCredential[],
  choice: ModelChoice | null,
): ResolvedChoice | null {
  const picked = choice && credentials.find((item) => item.id === choice.credentialId)
  if (picked && choice) return { credential: picked, model: choice.model, effort: choice.effort }
  const fallback = credentials.find((item) => item.is_default)
  if (fallback?.default_model) return { credential: fallback, model: fallback.default_model }
  return null
}

/**
 * «Claude Opus 5.5, тщательно, ключ «Рабочий»» или «Сервер по умолчанию». Уровень виден,
 * когда известны возможности модели и она умеет рассуждать.
 */
export function choiceLabel(
  credentials: LlmCredential[],
  choice: ModelChoice | null,
  caps?: ModelCapabilities,
): string {
  const resolved = resolveChoice(credentials, choice)
  if (!resolved) return SERVER_MODEL_LABEL
  const effort = effectiveEffort(resolved.effort, caps)
  const level = effort ? `${LABEL_SEPARATOR}${effortLabel(effort).toLowerCase()}` : ''
  return `${modelLabel(resolved.model)}${level}${LABEL_SEPARATOR}ключ «${resolved.credential.label}»`
}

/** Поля запроса запуска: без явного выбора сервер сам возьмёт ключ по умолчанию и уровень модели. */
export function choiceRequest(choice: ModelChoice | null): {
  credential_id?: string
  model?: string
  profile?: { effort: Effort }
} {
  if (!choice) return {}
  const request = { credential_id: choice.credentialId, model: choice.model }
  return choice.effort ? { ...request, profile: { effort: choice.effort } } : request
}
