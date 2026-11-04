import { useInfiniteQuery, useQuery } from '@tanstack/react-query'
import { useEffect, useId, useMemo, useRef, useState } from 'react'
import {
  diagramElements,
  elementTypeLabel,
  hasDiff,
  VERSION_ORIGIN,
  type VersionKind,
  type VersionSource,
  type VersionSummary,
  versionKind,
  versionLabel,
} from '@/entities/version'
import { cn } from '@/shared/lib/cn'
import { formatCount, formatDate, formatTime } from '@/shared/lib/format'
import { Badge, Button, Icon, type IconName, Sheet, SheetContent, Skeleton } from '@/shared/ui'
import { useWorkspace, useWorkspaceUi } from '@/widgets/workspace/model'

/** Дозагрузка следующей страницы, когда прокручено примерно 90% загруженного списка. */
const PREFETCH_AT = 0.9

const KIND: Record<VersionKind, { icon: IconName; label: string }> = {
  checkpoint: { icon: 'flag', label: 'Контрольная точка' },
  session: { icon: VERSION_ORIGIN.manual.icon, label: 'Правки' },
  build: { icon: VERSION_ORIGIN.generated.icon, label: 'Сборка по источникам' },
}

/**
 * История версий: именованные контрольные точки заметны, автосохранения сгруппированы в сессии
 * правок, сборки по источникам подписаны. Страницы подгружаются при прокрутке; старые версии —
 * только просмотр.
 */
export function VersionsSheet() {
  const { project, viewedVersionId, viewVersion, versions: source } = useWorkspace()
  const sheet = useWorkspaceUi((state) => state.sheet)
  const setSheet = useWorkspaceUi((state) => state.setSheet)
  const history = useInfiniteQuery({ ...source.pages(project.id), enabled: sheet === 'versions' })
  const items = useMemo(
    () => history.data?.pages.flatMap((page) => page.items) ?? [],
    [history.data],
  )
  const currentId = viewedVersionId ?? project.latest_version?.id
  const [expandedId, setExpandedId] = useState<string | null>(null)
  const { hasNextPage, isFetchingNextPage, fetchNextPage } = history
  const loadMore = () => {
    if (hasNextPage && !isFetchingNextPage) void fetchNextPage()
  }
  const sentinelIndex = Math.max(0, Math.ceil(items.length * PREFETCH_AT) - 1)

  return (
    <Sheet open={sheet === 'versions'} onOpenChange={(open) => setSheet(open ? 'versions' : null)}>
      <SheetContent size="sm" title="Версии схемы">
        {history.isPending ? (
          <div className="flex flex-col gap-3" aria-busy="true">
            {[0, 1, 2].map((key) => (
              <Skeleton key={key} className="h-20 rounded-lg" />
            ))}
          </div>
        ) : (
          <>
            <ol aria-label="Версии схемы" className="relative flex flex-col">
              {items.map((version, index) => (
                <VersionItem
                  key={version.id}
                  version={version}
                  latest={index === 0}
                  last={index === items.length - 1 && !hasNextPage}
                  current={version.id === currentId}
                  previous={items[index + 1]}
                  source={source}
                  expanded={expandedId === version.id}
                  onExpand={() => setExpandedId(expandedId === version.id ? null : version.id)}
                  onOpen={() => {
                    viewVersion(index === 0 ? undefined : version.id)
                    setSheet(null)
                  }}
                  sentinel={index === sentinelIndex && hasNextPage ? loadMore : undefined}
                />
              ))}
            </ol>
            {isFetchingNextPage && (
              <div className="mt-3 flex flex-col gap-3" aria-busy="true">
                <Skeleton className="h-20 rounded-lg" />
              </div>
            )}
            {hasNextPage && !isFetchingNextPage && typeof IntersectionObserver === 'undefined' && (
              <Button size="sm" variant="ghost" className="mt-3" onClick={loadMore}>
                Показать ещё
              </Button>
            )}
          </>
        )}
      </SheetContent>
    </Sheet>
  )
}

/** Вызывает `onVisible`, когда элемент попадает в область прокрутки. */
function useOnVisible(onVisible: (() => void) | undefined) {
  const ref = useRef<HTMLLIElement>(null)
  const callback = useRef(onVisible)
  callback.current = onVisible
  const active = Boolean(onVisible)
  useEffect(() => {
    const node = ref.current
    if (!active || !node || typeof IntersectionObserver === 'undefined') return
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries.some((entry) => entry.isIntersecting)) callback.current?.()
      },
      { rootMargin: '0px 0px 120px 0px' },
    )
    observer.observe(node)
    return () => observer.disconnect()
  }, [active])
  return ref
}

/** «14:05–14:32», а если сессия шла в разные дни, то с датой начала. */
function sessionRange(version: VersionSummary): string {
  const start = new Date(version.session_started_at)
  const end = new Date(version.updated_at)
  const sameDay = start.toDateString() === end.toDateString()
  const range =
    formatTime(start) === formatTime(end) && sameDay
      ? formatTime(start)
      : `${formatTime(start)}–${formatTime(end)}`
  return `${formatDate(start)}, ${range}`
}

function VersionItem({
  version,
  latest,
  last,
  current,
  onOpen,
  previous,
  source,
  expanded,
  onExpand,
  sentinel,
}: {
  version: VersionSummary
  latest: boolean
  last: boolean
  current: boolean
  onOpen: () => void
  previous?: VersionSummary
  source: VersionSource
  expanded: boolean
  onExpand: () => void
  sentinel?: () => void
}) {
  const kind = versionKind(version)
  const meta = KIND[kind]
  const panelId = useId()
  const ref = useOnVisible(sentinel)
  const title =
    kind === 'checkpoint'
      ? (version.label ?? meta.label)
      : kind === 'session'
        ? `Правки, ${sessionRange(version)}`
        : meta.label
  const date = new Date(version.created_at)
  const comparable = Boolean(previous) || version.number === 1
  return (
    <li ref={ref} className="relative flex gap-3 pb-4 last:pb-0">
      {!last && (
        <span aria-hidden="true" className="absolute top-7 bottom-0 left-3.5 w-px bg-border" />
      )}
      <span
        className={cn(
          'relative z-10 grid size-7 shrink-0 place-items-center rounded-full border bg-surface',
          current ? 'border-accent text-accent-fg shadow-glow' : 'border-border text-fg-subtle',
          kind === 'checkpoint' && !current && 'border-accent/40 text-accent-fg',
        )}
      >
        <Icon name={meta.icon} size={14} />
      </span>
      <div
        className={cn(
          'flex min-w-0 flex-1 flex-col gap-2 rounded-lg border px-3 py-2.5 transition-colors duration-base',
          current
            ? 'border-accent/40 bg-accent-subtle/50'
            : kind === 'checkpoint'
              ? 'border-accent/30'
              : 'border-border',
        )}
      >
        <div className="flex items-center gap-2">
          <span
            className={cn(
              'min-w-0 truncate text-fg',
              kind === 'checkpoint' ? 'type-subheading' : 'type-ui',
            )}
          >
            {title}
          </span>
          {latest && <Badge tone="accent">Последняя</Badge>}
        </div>
        <p className="type-caption text-fg-subtle" data-numeric>
          {versionLabel(version)}
          {kind !== 'session' && `, ${formatDate(date)}, ${formatTime(date)}`}
          {kind === 'session' &&
            version.saved_count > 1 &&
            `, ${formatCount(version.saved_count, ['автосохранение', 'автосохранения', 'автосохранений'])}`}
        </p>
        <div className="flex flex-wrap items-center gap-1.5">
          {hasDiff(version.diff) ? (
            <>
              {version.diff.added > 0 && <Badge tone="success">+{version.diff.added}</Badge>}
              {version.diff.removed > 0 && <Badge tone="danger">−{version.diff.removed}</Badge>}
              {version.diff.changed > 0 && (
                <Badge tone="amber">изменено {version.diff.changed}</Badge>
              )}
            </>
          ) : (
            version.number > 1 && (
              <span className="type-caption text-fg-subtle">Без изменений в узлах</span>
            )
          )}
          {version.assumption_count > 0 && (
            <Badge tone="amber" variant="outline" icon="assumption">
              {version.assumption_count}
            </Badge>
          )}
        </div>
        <p className="type-caption text-fg-muted">
          {version.actor_email ? `Автор: ${version.actor_email}` : 'Автор неизвестен'}
        </p>
        {comparable && (
          <Button
            size="sm"
            variant="ghost"
            trailingIcon={expanded ? 'chevron-up' : 'chevron-down'}
            className="self-start"
            aria-expanded={expanded}
            aria-controls={panelId}
            onClick={onExpand}
          >
            Что изменилось
          </Button>
        )}
        <div id={panelId} hidden={!expanded}>
          {expanded && <VersionChanges version={version} previous={previous} source={source} />}
        </div>
        {!current && (
          <Button
            size="sm"
            variant="ghost"
            trailingIcon="arrow-right"
            className="self-start"
            aria-label={`Открыть версию ${version.number}`}
            onClick={onOpen}
          >
            Открыть
          </Button>
        )}
      </div>
    </li>
  )
}

/** Подробности по именованным элементам, вычисленные из двух неизменяемых XML-версий. */
function VersionChanges({
  version,
  previous,
  source,
}: {
  version: VersionSummary
  previous?: VersionSummary
  source: VersionSource
}) {
  const current = useQuery(source.detail(version.id))
  const before = useQuery({ ...source.detail(previous?.id ?? version.id), enabled: !!previous })
  const currentXml = current.data?.xml
  const beforeXml = previous ? before.data?.xml : ''
  const changes = useMemo(() => {
    if (currentXml === undefined || beforeXml === undefined) return null
    const currentElements = diagramElements(currentXml)
    const beforeElements = diagramElements(beforeXml)
    return [
      ...[...currentElements.values()]
        .filter((element) => !beforeElements.has(element.id))
        .map((element) => ({ kind: 'Добавлено', element })),
      ...[...beforeElements.values()]
        .filter((element) => !currentElements.has(element.id))
        .map((element) => ({ kind: 'Удалено', element })),
      ...[...currentElements.values()]
        .filter((element) => {
          const old = beforeElements.get(element.id)
          return old && old.signature !== element.signature
        })
        .map((element) => ({ kind: 'Изменено', element })),
    ]
  }, [currentXml, beforeXml])
  if (current.isPending || (previous && before.isPending)) {
    return <Skeleton className="h-12 rounded-md" />
  }
  if (!changes) {
    return <p className="type-caption text-fg-muted">Не удалось загрузить сравнение версий</p>
  }
  return changes.length ? (
    <ul className="flex flex-col gap-1 border-t border-border pt-2">
      {changes.map(({ kind, element }) => (
        <li key={`${kind}-${element.id}`} className="type-caption text-fg-muted">
          <span
            className={
              kind === 'Добавлено'
                ? 'text-success-fg'
                : kind === 'Удалено'
                  ? 'text-danger-fg'
                  : 'text-amber-fg'
            }
          >
            {kind}
          </span>{' '}
          {elementTypeLabel(element.type).toLowerCase()} «{element.name || element.id}»
        </li>
      ))}
    </ul>
  ) : (
    <p className="type-caption text-fg-muted">Состав и подписи элементов не изменились</p>
  )
}
