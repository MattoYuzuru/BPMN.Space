import type { AuthMode } from '@/entities/session'
import { SignInForm } from '@/features/sign-in/sign-in-form'
import { ThemeSwitch } from '@/features/theme-switch/theme-switch'
import { useDocumentTitle } from '@/shared/hooks/use-document-title'
import { BrandMark, Card, EntryScene } from '@/shared/ui'

const TITLES: Record<AuthMode, string> = {
  login: 'Вход',
  register: 'Регистрация',
}

/** Экран входа: узкая карточка на сетке-подложке, как у пустых и ошибочных экранов. */
export function LoginScreen({
  mode,
  onModeChange,
  redirectTo,
}: {
  mode: AuthMode
  onModeChange: (mode: AuthMode) => void
  redirectTo: string
}) {
  useDocumentTitle(TITLES[mode])
  return (
    <EntryScene header={<ThemeSwitch compact />}>
      <div className="flex w-full max-w-sm flex-col items-center gap-6">
        <div className="flex flex-col items-center gap-4 text-center">
          <BrandMark size="lg" />
          <h1 className="type-title text-fg">Архитектор</h1>
        </div>
        <Card variant="elevated" padding="lg" className="w-full" data-lens-block>
          <SignInForm mode={mode} onModeChange={onModeChange} redirectTo={redirectTo} />
        </Card>
      </div>
    </EntryScene>
  )
}
