import { useState } from 'react'
import { type AgentClient, agentClientSetups, agentSetupMessage } from '@/entities/api-token'
import { CopyField, SegmentedControl } from '@/shared/ui'

/**
 * Подключение агента: готовое сообщение «прочитай инструкцию и подключись» для любого агента
 * и настройки под выбранный клиент. Секрет показывается один раз — вместе с этим блоком.
 */
export function AgentSetup({
  origin,
  mcpUrl,
  secret,
  onCopied,
}: {
  origin: string
  mcpUrl: string
  secret: string
  onCopied?: () => void
}) {
  const [client, setClient] = useState<AgentClient>('claude-code')
  const setups = agentClientSetups(mcpUrl, secret)
  const current = setups.find((item) => item.client === client) ?? setups[0]

  return (
    <div className="flex flex-col gap-4">
      <CopyField
        label="Сообщение для агента"
        value={agentSetupMessage(origin, secret)}
        multiline
        copyMessage="Сообщение скопировано"
        copyLabel="Копировать сообщение"
        hint="Отправьте своему агенту: он прочитает инструкцию, подключит сервер сам и расскажет, что дальше."
        onCopied={onCopied}
      />
      <div className="flex flex-col gap-2">
        <SegmentedControl<AgentClient>
          aria-label="Клиент агента"
          size="sm"
          value={client}
          onValueChange={setClient}
          options={setups.map((item) => ({ value: item.client, label: item.label }))}
        />
        {current && (
          <CopyField
            key={current.client}
            label={`Настройка для ${current.label === 'Другой' ? 'другого клиента' : current.label}`}
            value={current.value}
            multiline
            copyMessage="Скопировано"
            copyLabel="Копировать настройку"
            hint={current.hint}
            onCopied={onCopied}
          />
        )}
      </div>
    </div>
  )
}
