import type { Schemas } from '@/shared/api/client'

export type ApiToken = Schemas['ApiToken']
export type ApiTokenCreated = Schemas['ApiTokenCreated']
export type ApiScope = Schemas['ApiScope']

/** Права токена (RFC-0007) в порядке сервера; подписи — что разрешено агенту. */
export const API_SCOPES: { value: ApiScope; label: string; description: string }[] = [
  {
    value: 'projects:read',
    label: 'Чтение проектов',
    description: 'Схема, версии, вопросы, источники и журнал прогонов',
  },
  {
    value: 'questions:answer',
    label: 'Ответы на вопросы',
    description: 'Ответить на вопрос или отметить его неприменимым',
  },
  {
    value: 'projects:write',
    label: 'Изменение проектов',
    description: 'Создать и переименовать проект, сохранить правку схемы',
  },
  {
    value: 'sources:write',
    label: 'Добавление источников',
    description: 'Добавить и изменить источник',
  },
  {
    value: 'sources:delete',
    label: 'Удаление источников',
    description: 'Удалить источник проекта',
  },
  {
    value: 'runs:start',
    label: 'Запуск прогонов',
    description: 'Анализ, сборка и помощник на ваших ключах моделей',
  },
]

/** Минимум по умолчанию: чтение и ответы. */
export const DEFAULT_SCOPES: ApiScope[] = ['projects:read', 'questions:answer']

export const EXPIRY_OPTIONS: { value: string; label: string }[] = [
  { value: '7', label: '7 дней' },
  { value: '30', label: '30 дней' },
  { value: '90', label: '90 дней' },
  { value: '365', label: 'Год' },
]
export const DEFAULT_EXPIRY_DAYS = 30

export function scopeLabel(scope: ApiScope): string {
  return API_SCOPES.find((item) => item.value === scope)?.label ?? scope
}

/** Права в порядке `API_SCOPES`, без повторов. */
export function orderedScopes(scopes: readonly ApiScope[]): ApiScope[] {
  return API_SCOPES.map((item) => item.value).filter((scope) => scopes.includes(scope))
}

/** Адрес MCP-сервера продукта: тот же origin, путь `/mcp` (RFC-0007, шаг 2). */
export function mcpUrl(origin: string): string {
  return `${origin.replace(/\/+$/, '')}/mcp`
}

/** Готовая команда подключения Claude Code. */
export function mcpCommand(origin: string, secret: string): string {
  return `claude mcp add --transport http bpmn-space ${mcpUrl(origin)} --header "Authorization: Bearer ${secret}"`
}
