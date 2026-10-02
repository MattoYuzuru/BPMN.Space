/**
 * Форматирование чисел, дат и множественного числа для интерфейса на русском.
 * Правила — docs/frontend/styleguide.md, раздел «Тексты интерфейса».
 */

const LOCALE = 'ru-RU'

const numberFormat = new Intl.NumberFormat(LOCALE)
const dateFormat = new Intl.DateTimeFormat(LOCALE, { day: 'numeric', month: 'long' })
const dateYearFormat = new Intl.DateTimeFormat(LOCALE, {
  day: 'numeric',
  month: 'long',
  year: 'numeric',
})
const timeFormat = new Intl.DateTimeFormat(LOCALE, { hour: '2-digit', minute: '2-digit' })
const relativeFormat = new Intl.RelativeTimeFormat(LOCALE, { numeric: 'auto' })

/** 12 345 — неразрывный пробел между разрядами. */
export function formatNumber(value: number): string {
  return numberFormat.format(value)
}

/**
 * Выбор формы слова по числу: pluralRu(5, ['вопрос', 'вопроса', 'вопросов']) вернёт 'вопросов'.
 */
export function pluralRu(count: number, forms: readonly [string, string, string]): string {
  const n = Math.abs(count) % 100
  const n1 = n % 10
  if (n > 10 && n < 20) return forms[2]
  if (n1 > 1 && n1 < 5) return forms[1]
  if (n1 === 1) return forms[0]
  return forms[2]
}

/** «3 вопроса» — число и согласованное слово. */
export function formatCount(count: number, forms: readonly [string, string, string]): string {
  return `${formatNumber(count)} ${pluralRu(count, forms)}`
}

/** «1 октября», а для другого года — «1 октября 2025 г.». */
export function formatDate(date: Date, now: Date = new Date()): string {
  return date.getFullYear() === now.getFullYear()
    ? dateFormat.format(date)
    : dateYearFormat.format(date)
}

/** «14:05». */
export function formatTime(date: Date): string {
  return timeFormat.format(date)
}

/** «только что», «5 минут назад», «вчера», дальше — дата. */
export function formatRelative(date: Date, now: Date = new Date()): string {
  const seconds = Math.round((date.getTime() - now.getTime()) / 1000)
  const abs = Math.abs(seconds)
  if (abs < 45) return 'только что'
  if (abs < 3600) return relativeFormat.format(Math.round(seconds / 60), 'minute')
  if (abs < 86_400) return relativeFormat.format(Math.round(seconds / 3600), 'hour')
  if (abs < 172_800) return relativeFormat.format(Math.round(seconds / 86_400), 'day')
  return formatDate(date, now)
}

/** Длительность записи по-часовому: «0:07», «2:22», «1:02:05». */
export function formatClock(seconds: number): string {
  const total = Math.max(0, Math.floor(seconds))
  const hours = Math.floor(total / 3600)
  const minutes = Math.floor((total % 3600) / 60)
  const rest = String(total % 60).padStart(2, '0')
  return hours > 0 ? `${hours}:${String(minutes).padStart(2, '0')}:${rest}` : `${minutes}:${rest}`
}

const fractionFormat = new Intl.NumberFormat(LOCALE, { maximumFractionDigits: 1 })

/** Размер файла: «812 Б», «48 КБ», «1,4 МБ» (неразрывный пробел перед единицей). */
export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${formatNumber(bytes)} Б`
  const units = ['КБ', 'МБ', 'ГБ'] as const
  let value = bytes / 1024
  let unit = 0
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024
    unit += 1
  }
  const rounded = value >= 10 ? Math.round(value) : value
  return `${fractionFormat.format(rounded)} ${units[unit]}`
}

/** Длительность прогона: «12 с», «1 мин 05 с». */
export function formatDuration(ms: number): string {
  const total = Math.max(0, Math.round(ms / 1000))
  const minutes = Math.floor(total / 60)
  const seconds = total % 60
  if (minutes === 0) return `${seconds} с`
  return `${minutes} мин ${String(seconds).padStart(2, '0')} с`
}
