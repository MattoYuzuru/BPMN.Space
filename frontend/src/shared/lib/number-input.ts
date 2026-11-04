/**
 * Строгий разбор чисел из полей бюджета: человек вводит «100 000», «1 000,50», «10».
 * Буквы, минус и лишние разделители — ошибка, а не молчаливое усечение числа.
 */

const SPACES = /[\s\u00A0\u202F]/g
const MONEY = /^\d+(?:[.,]\d{1,2})?$/
const INTEGER = /^\d+$/

export interface ParsedNumber {
  /** Число или null для пустого поля. */
  value: number | null
  /** Текст ошибки для `Field`; null — всё в порядке. */
  error: string | null
}

function clean(text: string): string {
  return text.replace(SPACES, '')
}

/** Сумма в долларах: пробелы-разделители разрядов, точка или запятая, до двух знаков после. */
export function parseMoneyInput(text: string): ParsedNumber {
  const raw = clean(text)
  if (!raw) return { value: null, error: null }
  if (!MONEY.test(raw)) {
    return { value: null, error: 'Введите сумму числом: например, 10 или 1 000,50' }
  }
  return { value: Number(raw.replace(',', '.')), error: null }
}

/** Целое неотрицательное число: токены, минуты, запросы. */
export function parseIntegerInput(
  text: string,
  message = 'Введите целое число: например, 100 000',
): ParsedNumber {
  const raw = clean(text)
  if (!raw) return { value: null, error: null }
  if (!INTEGER.test(raw)) return { value: null, error: message }
  const value = Number(raw)
  if (!Number.isSafeInteger(value)) return { value: null, error: message }
  return { value, error: null }
}

/** Токены: только целое число. */
export function parseTokensInput(text: string): ParsedNumber {
  return parseIntegerInput(text, 'Введите целое число токенов: например, 100 000')
}
