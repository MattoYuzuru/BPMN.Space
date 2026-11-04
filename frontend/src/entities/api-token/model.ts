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

/** Публичная инструкция для ИИ-агентов: статический файл фронтенда (`public/agents.md`). */
export function agentGuideUrl(origin: string): string {
  return `${origin.replace(/\/+$/, '')}/agents.md`
}

export type AgentClient = 'claude-code' | 'codex' | 'cursor' | 'other'

export interface AgentClientSetup {
  client: AgentClient
  label: string
  /** Что скопировать: команда терминала или фрагмент файла настроек. */
  value: string
  hint: string
}

/**
 * Подключение MCP-сервера в популярных клиентах. Все варианты — Streamable HTTP и
 * заголовок `Authorization: Bearer`; OAuth сервер пока не поддерживает (RFC-0007, шаг 4).
 */
export function agentClientSetups(url: string, secret: string): AgentClientSetup[] {
  const bearer = `Bearer ${secret}`
  const cursor = { mcpServers: { 'bpmn-space': { url, headers: { Authorization: bearer } } } }
  return [
    {
      client: 'claude-code',
      label: 'Claude Code',
      value: `claude mcp add --transport http bpmn-space ${url} --header "Authorization: ${bearer}"`,
      hint: 'Вставьте в терминал: команда добавит MCP-сервер в Claude Code.',
    },
    {
      client: 'codex',
      label: 'Codex',
      value: `[mcp_servers.bpmn-space]\nurl = "${url}"\nhttp_headers = { "Authorization" = "${bearer}" }`,
      hint: 'Добавьте в ~/.codex/config.toml и перезапустите Codex.',
    },
    {
      client: 'cursor',
      label: 'Cursor',
      value: JSON.stringify(cursor, null, 2),
      hint: 'Добавьте в ~/.cursor/mcp.json (или .cursor/mcp.json проекта).',
    },
    {
      client: 'other',
      label: 'Другой',
      value: `URL: ${url}\nТранспорт: Streamable HTTP\nЗаголовок: Authorization: ${bearer}`,
      hint: 'Подойдёт любой клиент MCP с HTTP-транспортом и своим заголовком.',
    },
  ]
}

/** Сообщение для любого агента: прочитать инструкцию и подключиться самому. */
export function agentSetupMessage(origin: string, secret: string): string {
  return [
    `Подключи MCP-сервер BPMN Space по инструкции ${agentGuideUrl(origin)}.`,
    `Адрес сервера: ${mcpUrl(origin)}. Токен: ${secret}`,
    'Не сохраняй токен в репозиторий и логи. После подключения проверь доступ через list_projects и расскажи, что видишь.',
  ].join('\n')
}
