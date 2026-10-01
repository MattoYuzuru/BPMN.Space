import {
  PATTERNS,
  RU,
  SIMULATION_MESSAGES,
  SIMULATION_TITLES,
  translateEventLabel,
} from './i18n-ru'

type Replacements = Record<string, string | number | undefined>

/**
 * Сервис `translate` для bpmn-js и панели свойств: строка из словаря + подстановка `{name}`.
 * Неизвестная строка остаётся как есть — лучше английская подсказка, чем пустая.
 */
export function translate(template: string, replacements: Replacements = {}): string {
  const text = RU[template] ?? translateEventLabel(template) ?? template
  return text.replace(/\{([^}]+)\}/g, (_, key: string) => String(replacements[key] ?? `{${key}}`))
}

/** Модуль bpmn-js, подменяющий встроенный английский `translate`. */
export const TranslateModule = {
  translate: ['value', translate],
}

function byPattern(text: string, dictionary: Readonly<Record<string, string>>): string | undefined {
  for (const [pattern, format] of PATTERNS) {
    const match = pattern.exec(text)
    if (match)
      return format(...match.slice(1).map((group) => dictionary[group] ?? RU[group] ?? group))
  }
  return undefined
}

/** Сообщения симуляции токена (журнал, уведомления у элементов). */
export function translateSimulationMessage(text: string): string {
  return SIMULATION_MESSAGES[text] ?? byPattern(text, SIMULATION_MESSAGES) ?? text
}

/** Подсказки и статичные подписи в разметке симуляции и всплывающих меню. */
export function translateUiText(text: string): string | undefined {
  return SIMULATION_TITLES[text] ?? byPattern(text, SIMULATION_TITLES)
}
