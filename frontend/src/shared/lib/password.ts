/**
 * Генератор паролей для регистрации. Случайность — только `crypto.getRandomValues`,
 * выбор символа — с отбраковкой (без смещения по модулю).
 */

/** Алфавит без похожих символов: нет `l I 1 O 0 o`. */
export const PASSWORD_CLASSES = {
  lower: 'abcdefghijkmnpqrstuvwxyz',
  upper: 'ABCDEFGHJKLMNPQRSTUVWXYZ',
  digit: '23456789',
  symbol: '-_.!@#%+=',
} as const

const CLASS_LIST = Object.values(PASSWORD_CLASSES)
const ALL = CLASS_LIST.join('')

/** Длина по умолчанию: укладывается в правила сервера (12–128). */
export const DEFAULT_PASSWORD_LENGTH = 20

const UINT32_RANGE = 2 ** 32

/** Равномерное целое 0 ≤ n < max: значения из «хвоста» диапазона отбрасываются. */
function randomBelow(max: number): number {
  const limit = UINT32_RANGE - (UINT32_RANGE % max)
  const buffer = new Uint32Array(1)
  for (;;) {
    crypto.getRandomValues(buffer)
    const value = buffer[0] as number
    if (value < limit) return value % max
  }
}

const pick = (alphabet: string) => alphabet[randomBelow(alphabet.length)] as string

/**
 * Пароль заданной длины (по умолчанию 20): минимум по одной строчной, заглавной, цифре и символу,
 * остальное — из общего алфавита; порядок перемешан тасованием Фишера — Йетса.
 */
export function generatePassword(length = DEFAULT_PASSWORD_LENGTH): string {
  if (!Number.isInteger(length) || length < CLASS_LIST.length) {
    throw new RangeError(`Длина пароля — целое число не меньше ${CLASS_LIST.length}`)
  }
  const chars = CLASS_LIST.map(pick)
  while (chars.length < length) chars.push(pick(ALL))
  for (let i = chars.length - 1; i > 0; i--) {
    const j = randomBelow(i + 1)
    ;[chars[i], chars[j]] = [chars[j] as string, chars[i] as string]
  }
  return chars.join('')
}
