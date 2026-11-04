import { useState } from 'react'
import type { ApiToken } from '@/entities/api-token'
import type { LlmCredential } from '@/entities/llm-credential'
import type { AuthMode } from '@/entities/session'
import { AccountMenuFor } from '@/features/account-menu/account-menu'
import { TokenRow } from '@/features/api-tokens/agent-access-section'
import { CredentialRow } from '@/features/llm-credentials/credentials-section'
import { PickerBody } from '@/features/model-picker/model-picker'
import { SignInForm } from '@/features/sign-in/sign-in-form'
import { generatePassword } from '@/shared/lib/password'
import { Badge, BrandMark, Card, CopyField, Field, IconButton, Input, Tag } from '@/shared/ui'
import { Section, Specimen } from './kit'

/** Поле пароля регистрации: ключ создаёт пароль и показывает его (как в SignInForm). */
function PasswordGeneratorDemo() {
  const [value, setValue] = useState('')
  const [visible, setVisible] = useState(false)
  return (
    <div className="mx-auto w-full max-w-sm">
      <Field label="Пароль" hint="От 8 символов">
        <Input
          name="password"
          type={visible ? 'text' : 'password'}
          autoComplete="new-password"
          leadingIcon="lock"
          value={value}
          onChange={(event) => setValue(event.target.value)}
          trailing={
            <>
              <IconButton
                icon="key"
                size="sm"
                label="Сгенерировать надёжный пароль"
                onClick={() => {
                  setValue(generatePassword())
                  setVisible(true)
                }}
              />
              <IconButton
                icon={visible ? 'eye-off' : 'eye'}
                size="sm"
                label={visible ? 'Скрыть пароль' : 'Показать пароль'}
                tooltip={false}
                aria-pressed={visible}
                onClick={() => setVisible((current) => !current)}
              />
            </>
          }
        />
      </Field>
    </div>
  )
}

const DEMO_TOKEN: ApiToken = {
  id: 't1',
  name: 'Claude Code на ноутбуке',
  token_prefix: 'bps_tttttt',
  scopes: ['projects:read', 'questions:answer'],
  project_ids: null,
  expires_at: '2026-12-04T00:00:00Z',
  created_at: '2026-11-04T00:00:00Z',
  last_used_at: null,
  expired: false,
}

const DEMO_SECRET = 'bps_ttttttttttttttttttttttttttttttttttttttttttt'

const DEMO_CREDENTIALS: LlmCredential[] = [
  {
    id: 'k1',
    provider: 'anthropic',
    label: 'Рабочий',
    base_url: null,
    key_hint: 'a1b2',
    default_model: 'claude-opus-5-5',
    is_default: true,
    created_at: '2026-11-01T09:00:00Z',
    last_used_at: '2026-11-03T12:00:00Z',
    last_error: null,
  },
  {
    id: 'k2',
    provider: 'openai_compatible',
    label: 'OpenRouter',
    base_url: 'https://openrouter.ai/api/v1',
    key_hint: 'z9y8',
    default_model: 'deepseek/deepseek-chat',
    is_default: false,
    created_at: '2026-11-02T09:00:00Z',
    last_used_at: null,
    last_error: 'Провайдер отклонил ключ (HTTP 401). Проверьте ключ и доступ к модели в настройках',
  },
]

/** Аккаунт и доступ: карточка входа, меню аккаунта, маркеры режима «только просмотр». */
export function AccountSection() {
  const [mode, setMode] = useState<AuthMode>('login')
  return (
    <Section
      id="account"
      eyebrow="18 Аккаунт"
      title="Вход, меню аккаунта, только просмотр"
      lead="Экран входа — узкая карточка на сетке. Меню аккаунта живёт в шапке, а проект без прав на правку помечен спокойным маркером и не показывает действия, которые всё равно не сработают."
    >
      <Specimen title="Карточка входа">
        <div className="mx-auto flex w-full max-w-sm flex-col items-center gap-5 py-4">
          <BrandMark size="lg" />
          <Card variant="elevated" padding="lg" className="w-full">
            <SignInForm mode={mode} onModeChange={setMode} redirectTo="/styleguide" />
          </Card>
        </div>
      </Specimen>
      <Specimen title="Пароль при регистрации" note="IconButton icon=key + eye, generatePassword()">
        <PasswordGeneratorDemo />
        <p className="type-caption mt-3 text-fg-muted">
          Только в режиме «Регистрация», порядок «ключ, глаз». Нажатие подставляет надёжный пароль
          из 20 символов (без похожих l I 1 O 0 o), показывает его и копирует в буфер. На отправке
          поле снова скрывается, чтобы менеджер паролей предложил сохранить.
        </p>
      </Specimen>
      <Specimen title="Меню аккаунта">
        <AccountMenuFor
          user={{ id: 'demo', email: 'anna.petrova@company.ru' }}
          onLogout={() => {}}
        />
      </Specimen>
      <Specimen title="Модели и ключи" note="CredentialRow, Card, Badge, IconButton">
        <ul className="flex flex-col gap-2">
          {DEMO_CREDENTIALS.map((item) => (
            <li key={item.id}>
              <CredentialRow credential={item} onEdit={() => {}} onDelete={() => {}} />
            </li>
          ))}
        </ul>
        <p className="type-caption mt-3 text-fg-muted">
          Показывается только маска ключа. Ошибка последнего использования видна в строке, чтобы
          отозванный ключ находился сразу.
        </p>
      </Specimen>
      <Specimen title="Выбор модели при запуске" note="Popover, два Select, RadioGroup уровня">
        <div className="w-80 rounded-lg border border-border bg-surface p-4 shadow-sm">
          <PickerBody items={DEMO_CREDENTIALS} loading={false} choice={null} onChange={() => {}} />
        </div>
      </Specimen>
      <Specimen title="Доступ для агентов" note="TokenRow, CopyField, одноразовый секрет">
        <div className="flex flex-col gap-4">
          <TokenRow token={DEMO_TOKEN} projects={undefined} onRevoke={() => {}} />
          <CopyField
            label="Токен"
            value={DEMO_SECRET}
            copyLabel="Копировать токен"
            hint="Показывается один раз. Храните его как пароль."
          />
          <CopyField
            label="Команда для Claude Code"
            value={`claude mcp add --transport http bpmn-space https://bpmn.space/mcp --header "Authorization: Bearer ${DEMO_SECRET}"`}
            copyLabel="Копировать команду"
            multiline
            hint="MCP-сервер пока не запущен: команда заработает после обновления продукта."
          />
          <p className="type-caption text-fg-muted">
            Токен действует от имени владельца и только в пределах выбранных прав, проектов и срока.
            Отзыв мгновенный; секрет показывается один раз.
          </p>
        </div>
      </Specimen>
      <Specimen title="Только просмотр">
        <div className="flex flex-wrap items-center gap-3">
          <Badge tone="neutral" variant="outline" icon="lock">
            Только просмотр
          </Badge>
          <Tag icon="lock">Пример</Tag>
        </div>
      </Specimen>
    </Section>
  )
}
