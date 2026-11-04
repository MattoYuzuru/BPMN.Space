import type { Schemas } from '@/shared/api/client'

export type LlmCredential = Schemas['LlmCredential']
export type LlmProvider = LlmCredential['provider']
export type LlmModel = Schemas['LlmModel']

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

/** Явный выбор для запуска: ключ и модель. Не выбрано — ключ по умолчанию, затем сервер. */
export interface ModelChoice {
  credentialId: string
  model: string
}

export interface ResolvedChoice {
  credential: LlmCredential
  model: string
}

/** Что реально будет использовано: явный выбор, иначе ключ по умолчанию; `null` — сервер. */
export function resolveChoice(
  credentials: LlmCredential[],
  choice: ModelChoice | null,
): ResolvedChoice | null {
  const picked = choice && credentials.find((item) => item.id === choice.credentialId)
  if (picked && choice) return { credential: picked, model: choice.model }
  const fallback = credentials.find((item) => item.is_default)
  if (fallback?.default_model) return { credential: fallback, model: fallback.default_model }
  return null
}

/** «Claude Opus 5.5, ключ «Рабочий»» или «Сервер по умолчанию». */
export function choiceLabel(credentials: LlmCredential[], choice: ModelChoice | null): string {
  const resolved = resolveChoice(credentials, choice)
  if (!resolved) return SERVER_MODEL_LABEL
  return `${modelLabel(resolved.model)}${LABEL_SEPARATOR}ключ «${resolved.credential.label}»`
}

/** Поля запроса запуска: без явного выбора сервер сам возьмёт ключ по умолчанию. */
export function choiceRequest(choice: ModelChoice | null): {
  credential_id?: string
  model?: string
} {
  return choice ? { credential_id: choice.credentialId, model: choice.model } : {}
}
