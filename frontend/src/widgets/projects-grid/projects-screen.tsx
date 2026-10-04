import { keepPreviousData, useInfiniteQuery } from '@tanstack/react-query'
import { useEffect, useRef, useState } from 'react'
import { PROJECT_SCOPES, type ProjectScope, projectsInfiniteOptions } from '@/entities/project'
import { useSession } from '@/entities/session'
import { useCreateProjectDialog } from '@/features/create-project/model'
import { useDebouncedValue } from '@/shared/hooks/use-debounced'
import { useDocumentTitle } from '@/shared/hooks/use-document-title'
import { useHotkey } from '@/shared/hooks/use-hotkey'
import { formatNumber } from '@/shared/lib/format'
import { TOUR_ANCHORS, tourAnchor } from '@/shared/lib/tour-anchors'
import { Button, IconButton, Input, Kbd, SegmentedControl } from '@/shared/ui'
import { AppHeader } from '@/widgets/app-header/app-header'
import { ProjectsGrid } from './projects-grid'

const SEARCH_DEBOUNCE_MS = 250

export interface ProjectsScreenProps {
  query: string
  scope: ProjectScope
  onQueryChange: (query: string) => void
  onScopeChange: (scope: ProjectScope) => void
}

/** Экран «Проекты»: шапка с поиском, заголовок с действиями создания и сетка карточек. */
export function ProjectsScreen({
  query,
  scope,
  onQueryChange,
  onScopeChange,
}: ProjectsScreenProps) {
  const [draft, setDraft] = useState(query)
  const debounced = useDebouncedValue(draft.trim(), SEARCH_DEBOUNCE_MS)
  const searchRef = useRef<HTMLInputElement>(null)
  const showCreate = useCreateProjectDialog((state) => state.show)
  // Тот же запрос, что у сетки: данные из общего кэша, второго запроса нет.
  const total = useInfiniteQuery({
    ...projectsInfiniteOptions(query, scope),
    placeholderData: keepPreviousData,
    select: (data) => data.pages[0]?.total,
  })

  // Без аккаунтов проекты не делятся на свои и чужие — переключатель не нужен.
  const session = useSession()
  const scoped = session.data?.auth_enabled === true

  // Адрес — источник правды: «назад» в браузере возвращает и текст поиска.
  useEffect(() => setDraft(query), [query])
  useEffect(() => {
    if (debounced !== query) onQueryChange(debounced)
  }, [debounced, query, onQueryChange])

  useHotkey(['/'], () => searchRef.current?.focus())
  useDocumentTitle('Проекты')

  return (
    <div className="flex min-h-dvh flex-col bg-bg">
      <AppHeader className="sticky top-0">
        <div className="mx-auto w-full max-w-md">
          <Input
            ref={searchRef}
            type="search"
            size="sm"
            value={draft}
            leadingIcon="search"
            placeholder="Найти проект"
            aria-label="Поиск по проектам"
            onChange={(event) => setDraft(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === 'Escape') setDraft('')
            }}
            trailing={
              draft ? (
                <IconButton
                  icon="x"
                  size="sm"
                  label="Очистить поиск"
                  tooltip={false}
                  className="size-5"
                  onClick={() => setDraft('')}
                />
              ) : (
                <Kbd>/</Kbd>
              )
            }
          />
        </div>
      </AppHeader>
      <main className="mx-auto flex w-full max-w-[100rem] flex-1 flex-col gap-6 px-6 pt-8 pb-16 wide:px-10 wide:pt-10">
        <div className="flex flex-wrap items-end justify-between gap-4">
          <div className="flex items-center gap-4">
            <div className="flex items-baseline gap-3">
              <h1 className="type-title text-fg">Проекты</h1>
              {total.data !== undefined && (
                <span className="type-ui text-fg-subtle" data-numeric>
                  {formatNumber(total.data)}
                </span>
              )}
            </div>
            {scoped && (
              <SegmentedControl
                aria-label="Какие проекты показывать"
                size="sm"
                options={PROJECT_SCOPES}
                value={scope}
                onValueChange={onScopeChange}
              />
            )}
          </div>
          <div className="flex items-center gap-2">
            <Button leadingIcon="template" onClick={() => showCreate('example')}>
              Начать с примера
            </Button>
            <Button
              variant="primary"
              leadingIcon="plus"
              {...tourAnchor(TOUR_ANCHORS.projectsNew)}
              onClick={() => showCreate('blank')}
            >
              Новый проект
            </Button>
          </div>
        </div>
        <ProjectsGrid
          query={query}
          scope={scope}
          onResetQuery={() => setDraft('')}
          onResetScope={() => onScopeChange('all')}
        />
      </main>
    </div>
  )
}
