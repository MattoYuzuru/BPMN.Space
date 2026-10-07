/**
 * Заглушки экранов на время первой загрузки (pendingComponent маршрутов). Модуль входит
 * в стартовый бандл вместе с деревом маршрутов, поэтому импортирует только Skeleton
 * и знак — никаких виджетов экранов: иначе их код попал бы в стартовый чанк.
 */
import { BrandMark, Skeleton, SkeletonText } from '@/shared/ui'

/** Сетка карточек проектов: те же колонки, что у настоящей. */
export const PROJECTS_GRID = 'grid grid-cols-1 gap-3 @2xl:grid-cols-2 @5xl:grid-cols-3 wide:gap-4'

function HeaderSkeleton({ children }: { children?: React.ReactNode }) {
  return (
    <div className="flex h-14 shrink-0 items-center gap-3 border-b border-border bg-bg px-4 wide:px-5">
      <BrandMark />
      <div className="flex flex-1 items-center gap-3">{children}</div>
      <Skeleton className="h-6 w-24" />
    </div>
  )
}

/** Заглушка карточки той же высоты, что и настоящая. */
export function ProjectCardSkeleton() {
  return (
    <div className="flex h-full min-h-52 flex-col rounded-lg border border-border bg-surface">
      <div className="flex flex-1 flex-col gap-3 p-4">
        <Skeleton className="h-5 w-24" />
        <Skeleton className="h-4 w-4/5" />
        <Skeleton className="h-3 w-3/5" />
        <div className="mt-auto flex gap-1.5">
          <Skeleton className="h-6 w-20" />
          <Skeleton className="h-6 w-28" />
        </div>
      </div>
      <div className="flex gap-3 border-t border-border px-4 py-3">
        <Skeleton className="h-3 w-8" />
        <Skeleton className="h-3 w-8" />
        <Skeleton className="h-3 w-8" />
        <Skeleton className="ml-auto h-3 w-20" />
      </div>
    </div>
  )
}

export function ProjectsGridSkeleton() {
  return (
    <div className="@container" aria-busy="true">
      <div className={PROJECTS_GRID}>
        {Array.from({ length: 8 }, (_, index) => (
          // biome-ignore lint/suspicious/noArrayIndexKey: заглушки без идентичности
          <ProjectCardSkeleton key={index} />
        ))}
      </div>
    </div>
  )
}

export function ProjectsScreenSkeleton() {
  return (
    <div className="flex min-h-dvh flex-col bg-bg">
      <HeaderSkeleton>
        <Skeleton className="mx-auto h-7 w-full max-w-md" />
      </HeaderSkeleton>
      <main className="mx-auto flex w-full max-w-[100rem] flex-1 flex-col gap-6 px-6 pt-8 pb-16 wide:px-10 wide:pt-10">
        <div className="flex items-end justify-between">
          <Skeleton className="h-8 w-40" />
          <Skeleton className="h-8 w-64" />
        </div>
        <ProjectsGridSkeleton />
      </main>
    </div>
  )
}

/** Заглушка рабочего места: та же раскладка из трёх панелей, что у настоящего. */
export function WorkspaceSkeleton() {
  return (
    <div className="flex h-dvh flex-col bg-bg" aria-busy="true">
      <HeaderSkeleton>
        <Skeleton className="h-4 w-64" />
      </HeaderSkeleton>
      <div className="flex min-h-0 flex-1">
        <div className="flex w-1/5 min-w-56 flex-col gap-3 border-r border-border bg-bg-subtle p-4">
          <Skeleton className="h-4 w-24" />
          {[0, 1, 2].map((key) => (
            <div key={key} className="flex items-center gap-2.5">
              <Skeleton className="size-7 rounded-md" />
              <SkeletonText lines={2} className="flex-1" />
            </div>
          ))}
        </div>
        <div className="relative flex-1">
          <div className="absolute inset-0 pattern-dots opacity-60" />
        </div>
        <div className="flex w-1/4 min-w-72 flex-col gap-3 border-l border-border bg-surface p-4">
          <Skeleton className="h-4 w-28" />
          {[0, 1].map((key) => (
            <div key={key} className="flex flex-col gap-3 rounded-lg border border-border p-4">
              <Skeleton className="h-3 w-32" />
              <SkeletonText lines={2} />
              <Skeleton className="h-14 rounded-md" />
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}
