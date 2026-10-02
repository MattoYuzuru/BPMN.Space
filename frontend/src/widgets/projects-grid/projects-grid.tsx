import { keepPreviousData, useInfiniteQuery } from '@tanstack/react-query'
import { AnimatePresence, m } from 'motion/react'
import { PROJECTS_PAGE_SIZE, projectsInfiniteOptions } from '@/entities/project'
import { useCreateProjectDialog } from '@/features/create-project/model'
import { errorMessage } from '@/shared/api/client'
import { useGridColumns, useLoadMore } from '@/shared/hooks/use-load-more'
import { formatCount } from '@/shared/lib/format'
import { listItem, staggerDelay } from '@/shared/lib/motion'
import { Button, EmptyState } from '@/shared/ui'
import {
  PROJECTS_GRID as GRID,
  ProjectCardSkeleton,
  ProjectsGridSkeleton,
} from '@/widgets/skeletons/screen-skeletons'
import { ProjectCard } from './project-card'

export interface ProjectsGridProps {
  query: string
  onResetQuery: () => void
}

/**
 * Сетка проектов с бесконечной прокруткой. Следующая страница грузится, когда в окне
 * показалась карточка на ~90 % загруженного (useLoadMore). Пока идёт поиск, на экране
 * остаются прошлые результаты (keepPreviousData) — без мигания пустым состоянием.
 */
export function ProjectsGrid({ query, onResetQuery }: ProjectsGridProps) {
  const projects = useInfiniteQuery({
    ...projectsInfiniteOptions(query),
    placeholderData: keepPreviousData,
  })
  const items = projects.data?.pages.flatMap((page) => page.items) ?? []
  const total = projects.data?.pages[0]?.total ?? 0
  const { columns, gridRef } = useGridColumns<HTMLDivElement>()
  const { sentinelIndex, sentinelRef } = useLoadMore({
    loaded: items.length,
    hasNextPage: projects.hasNextPage,
    isFetching: projects.isFetchingNextPage,
    fetchNextPage: projects.fetchNextPage,
    columns,
  })
  const showCreate = useCreateProjectDialog((state) => state.show)

  if (projects.isPending) return <ProjectsGridSkeleton />

  if (projects.isError && items.length === 0) {
    return (
      <EmptyState
        icon="alert-circle"
        title="Список проектов не загрузился"
        description={errorMessage(projects.error)}
        action={<Button onClick={() => void projects.refetch()}>Повторить</Button>}
      />
    )
  }

  if (items.length === 0) {
    return query ? (
      <EmptyState
        icon="search-off"
        title="Ничего не найдено"
        description={`Проектов с «${query}» в названии нет.`}
        backdrop="dots"
        action={<Button onClick={onResetQuery}>Сбросить поиск</Button>}
      />
    ) : (
      <EmptyState
        icon="folder"
        title="Проектов пока нет"
        description="Проект — это один процесс: источники, вопросы и схема BPMN."
        action={
          <>
            <Button variant="primary" leadingIcon="plus" onClick={() => showCreate('blank')}>
              Новый проект
            </Button>
            <Button leadingIcon="template" onClick={() => showCreate('example')}>
              Начать с примера
            </Button>
          </>
        }
      />
    )
  }

  return (
    <section aria-label="Проекты" aria-busy={projects.isFetching || undefined}>
      <div className="@container">
        <div ref={gridRef} className={GRID}>
          <AnimatePresence>
            {items.map((project, index) => (
              <m.div
                key={project.id}
                ref={index === sentinelIndex ? sentinelRef : undefined}
                variants={listItem}
                initial="initial"
                animate="animate"
                exit="exit"
                transition={{ delay: staggerDelay(index % PROJECTS_PAGE_SIZE) }}
                className="h-full"
              >
                <ProjectCard project={project} />
              </m.div>
            ))}
          </AnimatePresence>
          {projects.isFetchingNextPage &&
            Array.from({ length: columns }, (_, index) => (
              // biome-ignore lint/suspicious/noArrayIndexKey: заглушки следующей страницы
              <ProjectCardSkeleton key={`more-${index}`} />
            ))}
        </div>
      </div>
      {!projects.hasNextPage && total > PROJECTS_PAGE_SIZE && (
        <p className="py-8 text-center type-caption text-fg-subtle" data-numeric>
          {formatCount(total, ['проект', 'проекта', 'проектов'])}
        </p>
      )}
    </section>
  )
}
