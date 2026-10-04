import { useState } from 'react'
import type { AuthMode } from '@/entities/session'
import { AccountMenuFor } from '@/features/account-menu/account-menu'
import { SignInForm } from '@/features/sign-in/sign-in-form'
import { Badge, BrandMark, Card, Tag } from '@/shared/ui'
import { Section, Specimen } from './kit'

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
