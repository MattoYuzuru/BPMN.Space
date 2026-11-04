import { AgentAccessSection } from '@/features/api-tokens/agent-access-section'
import { CredentialsSection } from '@/features/llm-credentials/credentials-section'
import { ToolsSection } from '@/features/tools-credentials/tools-section'
import { useDocumentTitle } from '@/shared/hooks/use-document-title'
import { AppHeader } from '@/widgets/app-header/app-header'

/** Экран «Настройки»: ключи инструментов, свои ключи моделей и токены доступа для агентов. */
export function SettingsPage() {
  useDocumentTitle('Настройки')
  return (
    <div className="flex min-h-dvh flex-col bg-bg">
      <AppHeader className="sticky top-0">
        <h1 className="type-subheading text-fg">Настройки</h1>
      </AppHeader>
      <main className="mx-auto flex w-full max-w-2xl flex-1 flex-col gap-12 px-4 py-8 wide:px-5">
        <ToolsSection />
        <CredentialsSection />
        <AgentAccessSection />
      </main>
    </div>
  )
}
