import { useState } from 'react'
import type { AuthMode } from '@/entities/session'
import { SignInForm } from '@/features/sign-in/sign-in-form'
import { ThemeSwitch } from '@/features/theme-switch/theme-switch'
import { useDocumentTitle } from '@/shared/hooks/use-document-title'
import { BrandMark, Card, GridBackdrop } from '@/shared/ui'

const TITLES: Record<AuthMode, string> = {
  login: 'Вход',
  register: 'Регистрация',
}

/** Экран входа: узкая карточка на сетке-подложке, как у пустых и ошибочных экранов. */
export function LoginScreen({ redirectTo }: { redirectTo: string }) {
  const [mode, setMode] = useState<AuthMode>('login')
  useDocumentTitle(TITLES[mode])
  return (
    <div className="flex min-h-dvh flex-col bg-bg">
      <header className="flex h-14 shrink-0 items-center justify-end px-4 wide:px-5">
        <ThemeSwitch compact />
      </header>
      <main className="relative isolate grid flex-1 place-items-center px-6 pb-16">
        <GridBackdrop pattern="grid" glow />
        <div className="flex w-full max-w-sm flex-col items-center gap-6">
          <div className="flex flex-col items-center gap-4 text-center">
            <BrandMark size="lg" />
            <h1 className="type-title text-fg">Архитектор</h1>
          </div>
          <Card variant="elevated" padding="lg" className="w-full">
            <SignInForm mode={mode} onModeChange={setMode} redirectTo={redirectTo} />
          </Card>
        </div>
      </main>
    </div>
  )
}
