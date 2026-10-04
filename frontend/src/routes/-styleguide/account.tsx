import { useState } from 'react'
import type { AuthMode } from '@/entities/session'
import { AccountMenuFor } from '@/features/account-menu/account-menu'
import { SignInForm } from '@/features/sign-in/sign-in-form'
import { generatePassword } from '@/shared/lib/password'
import { Badge, BrandMark, Card, Field, IconButton, Input, Tag } from '@/shared/ui'
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
