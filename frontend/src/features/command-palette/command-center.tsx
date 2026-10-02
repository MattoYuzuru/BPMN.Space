import { type InfiniteData, useQueryClient } from '@tanstack/react-query'
import { useNavigate } from '@tanstack/react-router'
import { useEffect } from 'react'
import { type ProjectPage, projectKeys } from '@/entities/project'
import { useCreateProjectDialog } from '@/features/create-project/model'
import { useHotkey } from '@/shared/hooks/use-hotkey'
import { useTheme } from '@/shared/lib/theme'
import { type CommandGroup, CommandPalette, preloadCommandPalette } from '@/shared/ui'
import { useCommandStore } from './model'

const RECENT_LIMIT = 5

/**
 * Палитра команд приложения (Ctrl+K / ⌘K): переходы, создание проекта, тема и команды
 * текущего экрана. Код палитры (cmdk) грузится лениво, заранее — когда браузер простаивает.
 */
export function CommandCenter() {
  const open = useCommandStore((state) => state.open)
  const setOpen = useCommandStore((state) => state.setOpen)
  const contextual = useCommandStore((state) => state.contextual)
  const showCreate = useCreateProjectDialog((state) => state.show)
  const navigate = useNavigate()
  const client = useQueryClient()
  const { setPreference } = useTheme()

  useHotkey(['mod', 'k'], () => setOpen(!useCommandStore.getState().open))

  useEffect(() => {
    const idle = window.requestIdleCallback ?? ((cb: () => void) => window.setTimeout(cb, 1500))
    idle(() => void preloadCommandPalette())
  }, [])

  // Группы собираются на каждый рендер: палитра перерисовывается только при открытии и смене команд.
  const groups = buildGroups()

  function buildGroups(): CommandGroup[] {
    const recent =
      client
        .getQueryData<InfiniteData<ProjectPage>>(projectKeys.list(''))
        ?.pages[0]?.items.slice(0, RECENT_LIMIT) ?? []
    const result: CommandGroup[] = [...Object.values(contextual)]
    result.push({
      heading: 'Переход',
      items: [
        {
          id: 'go-projects',
          label: 'Все проекты',
          icon: 'layout-grid',
          keywords: ['projects', 'главная', 'список'],
          onSelect: () => void navigate({ to: '/' }),
        },
        ...recent.map((project) => ({
          id: `go-${project.id}`,
          label: project.title,
          icon: 'folder' as const,
          keywords: ['открыть', 'проект'],
          onSelect: () =>
            void navigate({ to: '/projects/$projectId', params: { projectId: project.id } }),
        })),
        {
          id: 'go-styleguide',
          label: 'Открыть стайлгайд',
          icon: 'palette',
          keywords: ['styleguide', 'дизайн-система', 'компоненты'],
          onSelect: () => void navigate({ to: '/styleguide' }),
        },
      ],
    })
    result.push({
      heading: 'Создать',
      items: [
        {
          id: 'create-blank',
          label: 'Новый проект',
          icon: 'folder-plus',
          keywords: ['create', 'создать'],
          onSelect: () => showCreate('blank'),
        },
        {
          id: 'create-example',
          label: 'Проект из примера',
          icon: 'template',
          keywords: ['example', 'демо', 'пример'],
          onSelect: () => showCreate('example'),
        },
      ],
    })
    result.push({
      heading: 'Тема',
      items: [
        {
          id: 'theme-light',
          label: 'Светлая тема',
          icon: 'sun',
          keywords: ['theme', 'light'],
          onSelect: () => setPreference('light'),
        },
        {
          id: 'theme-dark',
          label: 'Тёмная тема',
          icon: 'moon',
          keywords: ['theme', 'dark', 'ночь'],
          onSelect: () => setPreference('dark'),
        },
        {
          id: 'theme-system',
          label: 'Тема как в системе',
          icon: 'device-desktop',
          keywords: ['theme', 'system', 'авто'],
          onSelect: () => setPreference('system'),
        },
      ],
    })
    return result
  }

  return <CommandPalette open={open} onOpenChange={setOpen} groups={groups} />
}
