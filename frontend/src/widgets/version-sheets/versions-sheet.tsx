import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import {
  diagramElements,
  elementTypeLabel,
  hasDiff,
  VERSION_ORIGIN,
  type Version,
  type VersionSource,
  versionLabel,
} from '@/entities/version'
import { cn } from '@/shared/lib/cn'
import { formatDate, formatTime } from '@/shared/lib/format'
import { Badge, Button, Icon, Sheet, SheetContent, Skeleton } from '@/shared/ui'
import { useWorkspace, useWorkspaceUi } from '@/widgets/workspace/model'

/** История версий схемы: таймлайн с происхождением, датой и диффом; старые — только просмотр. */
export function VersionsSheet() {
  const { project, viewedVersionId, viewVersion, versions: source } = useWorkspace()
  const sheet = useWorkspaceUi((state) => state.sheet)
  const setSheet = useWorkspaceUi((state) => state.setSheet)
  const versions = useQuery({ ...source.list(project.id), enabled: sheet === 'versions' })
  const currentId = viewedVersionId ?? project.latest_version?.id
  const [expandedId, setExpandedId] = useState<string | null>(null)

  return (
    <Sheet open={sheet === 'versions'} onOpenChange={(open) => setSheet(open ? 'versions' : null)}>
      <SheetContent size="sm" title="Версии схемы">
        {versions.isPending ? (
          <div className="flex flex-col gap-3" aria-busy="true">
            {[0, 1, 2].map((key) => (
              <Skeleton key={key} className="h-20 rounded-lg" />
            ))}
          </div>
        ) : (
          <ol aria-label="Версии схемы" className="relative flex flex-col">
            {(versions.data ?? []).map((version, index, list) => (
              <VersionItem
                key={version.id}
                version={version}
                latest={index === 0}
                last={index === list.length - 1}
                current={version.id === currentId}
                previous={list[index + 1]}
                source={source}
                expanded={expandedId === version.id}
                onExpand={() => setExpandedId(expandedId === version.id ? null : version.id)}
                onOpen={() => {
                  viewVersion(index === 0 ? undefined : version.id)
                  setSheet(null)
                }}
              />
            ))}
          </ol>
        )}
      </SheetContent>
    </Sheet>
  )
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
}: {
  version: Version
  latest: boolean
  last: boolean
  current: boolean
  onOpen: () => void
  previous?: Version
  source: VersionSource
  expanded: boolean
  onExpand: () => void
}) {
  const origin = VERSION_ORIGIN[version.origin]
  const date = new Date(version.created_at)
  return (
    <li className="relative flex gap-3 pb-4 last:pb-0">
      {!last && (
        <span aria-hidden="true" className="absolute top-7 bottom-0 left-3.5 w-px bg-border" />
      )}
      <span
        className={cn(
          'relative z-10 grid size-7 shrink-0 place-items-center rounded-full border bg-surface',
          current ? 'border-accent text-accent-fg shadow-glow' : 'border-border text-fg-subtle',
        )}
      >
        <Icon name={origin.icon} size={14} />
      </span>
      <div
        className={cn(
          'flex min-w-0 flex-1 flex-col gap-2 rounded-lg border px-3 py-2.5 transition-colors duration-base',
          current ? 'border-accent/40 bg-accent-subtle/50' : 'border-border',
        )}
      >
        <div className="flex items-center gap-2">
          <span className="type-subheading text-fg">{versionLabel(version)}</span>
          {latest && <Badge tone="accent">Последняя</Badge>}
          <span className="ml-auto type-caption text-fg-subtle" data-numeric>
            {formatDate(date)}, {formatTime(date)}
          </span>
        </div>
        <div className="flex flex-wrap items-center gap-1.5">
          <Badge tone={origin.tone} variant="outline" icon={origin.icon}>
            {origin.label}
          </Badge>
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
          {version.report.assumptions.length > 0 && (
            <Badge tone="amber" variant="outline" icon="assumption">
              {version.report.assumptions.length}
            </Badge>
          )}
        </div>
        <p className="type-caption text-fg-muted">
          {version.actor_email ? `Автор: ${version.actor_email}` : 'Автор неизвестен'}
        </p>
        <Button
          size="sm"
          variant="ghost"
          trailingIcon={expanded ? 'chevron-up' : 'chevron-down'}
          className="self-start"
          onClick={onExpand}
        >
          Что изменилось
        </Button>
        {expanded && <VersionChanges version={version} previous={previous} source={source} />}
        {!current && (
          <Button
            size="sm"
            variant="ghost"
            trailingIcon="arrow-right"
            className="self-start"
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
  version: Version
  previous?: Version
  source: VersionSource
}) {
  const current = useQuery(source.detail(version.id))
  const before = useQuery({ ...source.detail(previous?.id ?? version.id), enabled: !!previous })
  if (current.isPending || (previous && before.isPending)) {
    return <Skeleton className="h-12 rounded-md" />
  }
  if (!current.data || (previous && !before.data)) {
    return <p className="type-caption text-fg-muted">Не удалось загрузить сравнение версий</p>
  }
  const currentElements = diagramElements(current.data.xml)
  const beforeElements = diagramElements(before.data?.xml ?? '')
  const changes = [
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
