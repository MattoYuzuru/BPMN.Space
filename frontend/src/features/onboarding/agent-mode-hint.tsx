import { useState } from 'react'
import { Button, Card, Icon } from '@/shared/ui'

const STORAGE_KEY = 'arkhitektor:agent-mode-hint-dismissed'

function wasDismissed(): boolean {
  try {
    return window.localStorage.getItem(STORAGE_KEY) === '1'
  } catch {
    return false
  }
}

/**
 * Клиентская подсказка об агентном режиме (RFC-0004) в диалоге запуска. Это не шаг серверного
 * тура из 11 шагов: показывается один раз, запоминает закрытие локально и не ломает сценарий.
 */
export function AgentModeHint({ enabled }: { enabled: boolean }) {
  const [dismissed, setDismissed] = useState(wasDismissed)
  if (!enabled || dismissed) return null
  const dismiss = () => {
    setDismissed(true)
    try {
      window.localStorage.setItem(STORAGE_KEY, '1')
    } catch {
      // Приватный режим: просто скрываем до перезагрузки.
    }
  }
  return (
    <Card
      variant="sunken"
      padding="sm"
      className="flex items-start gap-2.5"
      data-testid="agent-mode-hint"
    >
      <Icon name="bolt" size={16} className="mt-0.5 shrink-0 text-accent-fg" />
      <div className="flex min-w-0 flex-1 flex-col gap-1.5">
        <p className="type-ui text-fg">
          Новое: агентный режим — модель сама читает источники инструментами
        </p>
        <p className="type-caption text-fg-muted">
          Подходит для сложных наборов материалов. Дороже конвейера, но гибче; шаги и бюджет
          ограничены, на лимите прогон остановится и спросит, что делать.
        </p>
        <span>
          <Button size="sm" variant="ghost" onClick={dismiss}>
            Понятно
          </Button>
        </span>
      </div>
    </Card>
  )
}
