import { createFileRoute } from '@tanstack/react-router'
import { SettingsPage } from '@/widgets/settings-page/settings-page'

/** Настройки аккаунта; охрана входа — в родительском `_app`. */
export const Route = createFileRoute('/_app/settings')({
  component: SettingsPage,
})
