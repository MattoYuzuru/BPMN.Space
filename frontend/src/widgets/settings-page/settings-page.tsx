import { CredentialsSection } from '@/features/llm-credentials/credentials-section'
import { useDocumentTitle } from '@/shared/hooks/use-document-title'
import { AppHeader } from '@/widgets/app-header/app-header'

/** Экран «Настройки»: пока один раздел — свои ключи моделей. */
export function SettingsPage() {
  useDocumentTitle('Настройки')
  return (
    <div className="flex min-h-dvh flex-col bg-bg">
      <AppHeader className="sticky top-0">
        <h1 className="type-subheading text-fg">Настройки</h1>
      </AppHeader>
      <main className="mx-auto w-full max-w-2xl flex-1 px-4 py-8 wide:px-5">
        <CredentialsSection />
      </main>
    </div>
  )
}
