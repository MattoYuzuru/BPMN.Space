import { type KeyboardEvent, type ReactNode, useEffect, useMemo, useRef, useState } from 'react'
import { cn } from '@/shared/lib/cn'
import { Icon, type IconName } from '../icon'

export interface TreeItem {
  id: string
  label: ReactNode
  /** Иконка слева от подписи. */
  icon?: IconName
  /** Элементы справа: бейдж «ИИ», стоимость, статус. */
  meta?: ReactNode
  children?: TreeItem[]
  disabled?: boolean
}

export interface TreeViewProps {
  items: TreeItem[]
  /** Подпись дерева для скринридера. */
  label: string
  /** Выбранный узел. */
  selectedId?: string | null
  onSelect?: (id: string) => void
  /** Раскрытые узлы. Без пропа ветки раскрыты по умолчанию (дерево материалов). */
  expandedIds?: string[]
  defaultExpandedIds?: string[]
  onExpandedChange?: (ids: string[]) => void
  emptyLabel?: ReactNode
  className?: string
}

interface Row {
  item: TreeItem
  level: number
  parentId: string | null
  hasChildren: boolean
  expanded: boolean
}

function childrenOf(item: TreeItem): TreeItem[] {
  return item.children ?? []
}

function flatten(items: readonly TreeItem[], expanded: ReadonlySet<string>): Row[] {
  const rows: Row[] = []
  const walk = (list: readonly TreeItem[], level: number, parentId: string | null) => {
    for (const item of list) {
      const children = childrenOf(item)
      const hasChildren = children.length > 0
      const open = hasChildren && expanded.has(item.id)
      rows.push({ item, level, parentId, hasChildren, expanded: open })
      if (open) walk(children, level + 1, item.id)
    }
  }
  walk(items, 1, null)
  return rows
}

function allIds(items: readonly TreeItem[]): string[] {
  return items.flatMap((item) => [item.id, ...allIds(childrenOf(item))])
}

function withChildrenIds(items: readonly TreeItem[]): string[] {
  return items.flatMap((item) => [
    ...(childrenOf(item).length > 0 ? [item.id] : []),
    ...withChildrenIds(childrenOf(item)),
  ])
}

/**
 * Дерево с ARIA `tree`/`treeitem`: клавиатура идёт по видимым строкам, стрелки раскрывают ветки,
 * Home/End прыгают к краям. Клик выбирает узел, клик по стрелке раскрывает или сворачивает.
 */
export function TreeView({
  items,
  label,
  selectedId = null,
  onSelect,
  expandedIds,
  defaultExpandedIds,
  onExpandedChange,
  emptyLabel = 'Здесь пока ничего нет',
  className,
}: TreeViewProps) {
  const controlled = expandedIds !== undefined
  const [ownExpanded, setOwnExpanded] = useState<ReadonlySet<string>>(
    () => new Set(defaultExpandedIds ?? withChildrenIds(items)),
  )
  const expanded = useMemo(
    () => (controlled ? new Set(expandedIds) : ownExpanded),
    [controlled, expandedIds, ownExpanded],
  )
  const rows = useMemo(() => flatten(items, expanded), [items, expanded])
  const visibleIds = useMemo(() => rows.map((row) => row.item.id), [rows])
  const [focusedId, setFocusedId] = useState<string | null>(null)
  // Дерево может прийти асинхронно: до первого фокуса активная строка вычисляется на рендере,
  // иначе при пустых данных у всех строк tabIndex=-1 и в дерево нельзя попасть с клавиатуры.
  const activeId = focusedId ?? selectedId ?? visibleIds[0] ?? null
  const refs = useRef(new Map<string, HTMLDivElement>())
  const pendingFocus = useRef(false)
  const knownIds = useRef<ReadonlySet<string>>(new Set())
  const mounted = useRef(false)

  // Узел могли свернуть или убрать: фокус переезжает на первую видимую строку.
  useEffect(() => {
    if (focusedId && visibleIds.includes(focusedId)) return
    const next =
      selectedId && visibleIds.includes(selectedId) ? selectedId : (visibleIds[0] ?? null)
    if (next !== focusedId) setFocusedId(next)
  }, [focusedId, selectedId, visibleIds])

  // Дерево материалов приходит частями: новые ветки раскрываем, уже свёрнутые пользователем — нет.
  useEffect(() => {
    const ids = new Set(allIds(items))
    if (!mounted.current) {
      mounted.current = true
      knownIds.current = ids
      return
    }
    const fresh = new Set([...ids].filter((id) => !knownIds.current.has(id)))
    knownIds.current = ids
    if (controlled || fresh.size === 0) return
    const expandable = withChildrenIds(items).filter((id) => fresh.has(id))
    if (expandable.length === 0) return
    setOwnExpanded((previous) => {
      const next = new Set(previous)
      for (const id of expandable) next.add(id)
      return next
    })
  }, [items, controlled])

  // Фокус ставим после перерисовки: строка могла только что появиться.
  useEffect(() => {
    if (!pendingFocus.current || !focusedId) return
    pendingFocus.current = false
    refs.current.get(focusedId)?.focus()
  }, [focusedId])

  const setExpanded = (next: ReadonlySet<string>) => {
    if (!controlled) setOwnExpanded(next)
    onExpandedChange?.([...next])
  }

  const toggle = (id: string) => {
    const next = new Set(expanded)
    if (next.has(id)) next.delete(id)
    else next.add(id)
    setExpanded(next)
  }

  const focusItem = (id: string | undefined) => {
    if (!id) return
    pendingFocus.current = true
    setFocusedId(id)
  }

  const rowAt = (id: string | null) => rows.find((row) => row.item.id === id)

  const handleKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    // Строка берётся из события: клик мышью мог ещё не перерисовать состояние фокуса.
    const currentId = event.currentTarget.dataset.treeId ?? activeId
    if (!currentId) return
    const index = visibleIds.indexOf(currentId)
    const row = rowAt(currentId)
    if (!row) return
    switch (event.key) {
      case 'ArrowDown':
        event.preventDefault()
        focusItem(visibleIds[index + 1])
        break
      case 'ArrowUp':
        event.preventDefault()
        focusItem(visibleIds[index - 1])
        break
      case 'ArrowRight':
        event.preventDefault()
        if (row.hasChildren && !row.expanded) toggle(row.item.id)
        else if (row.expanded) {
          const child = rows[index + 1]
          if (child && child.level === row.level + 1) focusItem(child.item.id)
        }
        break
      case 'ArrowLeft':
        event.preventDefault()
        if (row.hasChildren && row.expanded) toggle(row.item.id)
        else focusItem(row.parentId ?? undefined)
        break
      case 'Home':
        event.preventDefault()
        focusItem(visibleIds[0])
        break
      case 'End':
        event.preventDefault()
        focusItem(visibleIds[visibleIds.length - 1])
        break
      case 'Enter':
      case ' ':
        event.preventDefault()
        if (row.item.disabled) break
        onSelect?.(row.item.id)
        if (event.key === 'Enter' && row.hasChildren) toggle(row.item.id)
        break
    }
  }

  if (rows.length === 0) {
    return <p className={cn('type-ui px-2 py-1.5 text-fg-subtle', className)}>{emptyLabel}</p>
  }

  return (
    <div role="tree" aria-label={label} className={cn('flex w-full flex-col gap-0.5', className)}>
      {rows.map((row) => {
        const selected = selectedId === row.item.id
        const focused = activeId === row.item.id
        return (
          <div
            key={row.item.id}
            role="treeitem"
            aria-level={row.level}
            aria-selected={selected}
            aria-expanded={row.hasChildren ? row.expanded : undefined}
            aria-disabled={row.item.disabled || undefined}
            data-tree-id={row.item.id}
            data-state={row.expanded ? 'open' : 'closed'}
            data-selected={selected || undefined}
            tabIndex={focused ? 0 : -1}
            ref={(node) => {
              if (node) refs.current.set(row.item.id, node)
              else refs.current.delete(row.item.id)
            }}
            onKeyDown={handleKeyDown}
            onFocus={() => setFocusedId(row.item.id)}
            onClick={(event) => {
              if (row.item.disabled) return
              // Стрелка раскрывает ветку, клик по остальной строке выбирает узел.
              if ((event.target as Element).closest('[data-part="chevron"]')) toggle(row.item.id)
              else onSelect?.(row.item.id)
            }}
            className={cn(
              'flex h-8 w-full cursor-pointer items-center gap-1.5 rounded-md pr-2 text-left outline-none',
              'transition-colors duration-base ease-soft hover:bg-hover',
              'focus-visible:ring-2 focus-visible:ring-focus-ring focus-visible:ring-inset',
              selected && 'bg-pressed',
              row.item.disabled && 'cursor-not-allowed opacity-45',
            )}
            style={{ paddingLeft: (row.level - 1) * 16 + 4 }}
          >
            {row.hasChildren ? (
              <span
                aria-hidden="true"
                data-part="chevron"
                className="grid size-4 shrink-0 cursor-pointer place-items-center text-fg-subtle"
              >
                <Icon
                  name="chevron-right"
                  size={14}
                  className={cn(
                    'transition-transform duration-base ease-soft',
                    row.expanded && 'rotate-90',
                  )}
                />
              </span>
            ) : (
              <span aria-hidden="true" className="size-4 shrink-0" />
            )}
            {row.item.icon && (
              <Icon name={row.item.icon} size={14} className="shrink-0 text-fg-subtle" />
            )}
            <span
              className={cn(
                'min-w-0 flex-1 truncate type-ui',
                selected ? 'text-fg' : 'text-fg-muted',
              )}
            >
              {row.item.label}
            </span>
            {row.item.meta && (
              <span className="flex shrink-0 items-center gap-1.5">{row.item.meta}</span>
            )}
          </div>
        )
      })}
    </div>
  )
}
