import { useEffect, useState } from 'react'
import {
  CHECKLIST_TOTAL,
  type ChecklistGroupView,
  type ChecklistItemKey,
  type ChecklistItemMeta,
  groupedChecklistItems,
} from '@/entities/onboarding'
import { cn } from '@/shared/lib/cn'
import { Button, DoneMark, Icon, Progress } from '@/shared/ui'
import { isRecent, useRecentItems } from './recent'

export interface ChecklistBodyProps {
  doneKeys: ReadonlySet<ChecklistItemKey>
  /** Идёт тур: пункты недоступны, пока он не закончится. */
  locked?: boolean
  /** Пункт, по которому сейчас идёт запрос «куда вести». */
  pending?: ChecklistItemKey | null
  /** Пункты, отмеченные только что (по умолчанию — из `OnboardingWatcher`). */
  recentAt?: Partial<Record<ChecklistItemKey, number>>
  onVisit: (item: ChecklistItemKey) => void
}

/** Содержимое панели «Начало работы»: прогресс и четыре группы пунктов. */
export function ChecklistBody({
  doneKeys,
  locked = false,
  pending = null,
  recentAt,
  onVisit,
}: ChecklistBodyProps) {
  const watched = useRecentItems((state) => state.at)
  const recent = recentAt ?? watched
  const done = doneKeys.size
  const complete = done >= CHECKLIST_TOTAL
  return (
    <div className="flex flex-col gap-5">
      <div className="flex flex-col gap-2">
        <div className="flex items-baseline justify-between gap-3">
          <span className="type-ui text-fg" data-numeric>
            {complete ? 'Все шаги выполнены' : `${done} из ${CHECKLIST_TOTAL}`}
          </span>
          {locked && <span className="type-caption text-fg-subtle">Доступно после обучения</span>}
        </div>
        <Progress
          value={done}
          max={CHECKLIST_TOTAL}
          tone={complete ? 'success' : 'accent'}
          label={`Выполнено ${done} из ${CHECKLIST_TOTAL}`}
        />
      </div>
      {groupedChecklistItems().map((group) => (
        <ChecklistGroup
          key={group.key}
          group={group}
          doneKeys={doneKeys}
          locked={locked}
          pending={pending}
          recent={recent}
          onVisit={onVisit}
        />
      ))}
    </div>
  )
}

function ChecklistGroup({
  group,
  doneKeys,
  locked,
  pending,
  recent,
  onVisit,
}: {
  group: ChecklistGroupView
  doneKeys: ReadonlySet<ChecklistItemKey>
  locked: boolean
  pending: ChecklistItemKey | null
  recent: Partial<Record<ChecklistItemKey, number>>
  onVisit: (item: ChecklistItemKey) => void
}) {
  const doneInGroup = group.items.filter((item) => doneKeys.has(item.key)).length
  return (
    <section aria-label={group.title} className="flex flex-col gap-1">
      <div className="flex items-baseline justify-between px-2">
        <h3 className="type-label text-fg-muted">{group.title}</h3>
        <span className="type-caption text-fg-subtle" data-numeric>
          {doneInGroup}/{group.items.length}
        </span>
      </div>
      <ul className="flex flex-col">
        {group.items.map((item) => (
          <ChecklistRow
            key={item.key}
            item={item}
            done={doneKeys.has(item.key)}
            recent={isRecent(recent, item.key)}
            locked={locked}
            busy={pending === item.key}
            blocked={pending !== null}
            onVisit={onVisit}
          />
        ))}
      </ul>
    </section>
  )
}

/**
 * Строка пункта. Выполненная — просто текст (отметить руками нельзя, пункт отмечает система);
 * невыполненная — вся строка кнопка, при наведении справа стрелка. Только что выполненная
 * проявляет галочку и зачёркивание за 320 мс (при `prefers-reduced-motion` — сразу).
 */
function ChecklistRow({
  item,
  done,
  recent,
  locked,
  busy,
  blocked,
  onVisit,
}: {
  item: ChecklistItemMeta
  done: boolean
  recent: boolean
  locked: boolean
  busy: boolean
  blocked: boolean
  onVisit: (item: ChecklistItemKey) => void
}) {
  // Состояние отметки задаём сами и меняем через два кадра: при смене строки с кнопки на текст
  // узлы создаются заново, и без этого переход (галочка, зачёркивание) не был бы виден.
  // Выполненный раньше пункт рисуется готовым сразу.
  const [shown, setShown] = useState(done && !recent)
  useEffect(() => {
    if (!done) {
      setShown(false)
      return
    }
    let second = 0
    const first = requestAnimationFrame(() => {
      second = requestAnimationFrame(() => setShown(true))
    })
    return () => {
      cancelAnimationFrame(first)
      cancelAnimationFrame(second)
    }
  }, [done])

  const content = (
    <>
      <DoneMark done={shown} />
      <span className="relative inline-block max-w-full min-w-0 truncate type-ui">
        <span
          className={cn(
            'transition-colors duration-slow ease-soft motion-reduce:transition-none',
            shown ? 'text-fg-subtle' : 'text-fg',
          )}
        >
          {item.title}
        </span>
        <span
          aria-hidden="true"
          className={cn(
            'absolute top-1/2 left-0 h-px w-full origin-left bg-fg-subtle',
            'transition-transform duration-slow ease-soft motion-reduce:transition-none',
            shown ? 'scale-x-100' : 'scale-x-0',
          )}
        />
        <span className="sr-only">{done ? ', выполнено' : ', не выполнено'}</span>
      </span>
    </>
  )

  if (done) {
    return (
      <li className="flex min-h-9 items-center gap-3 rounded-md px-2 py-1.5" data-item={item.key}>
        {content}
      </li>
    )
  }
  return (
    <li data-item={item.key}>
      <Button
        variant="ghost"
        disabled={locked}
        aria-busy={busy || undefined}
        aria-disabled={blocked || undefined}
        onClick={() => {
          if (!blocked) onVisit(item.key)
        }}
        className="group/row h-auto min-h-9 w-full justify-start rounded-md px-2 py-1.5 font-normal text-fg [&>span]:w-full [&>span]:gap-3"
      >
        {content}
        <Icon
          name="arrow-right"
          size={16}
          className="ml-auto text-fg-subtle opacity-0 transition-opacity duration-base group-hover/row:opacity-100 group-focus-visible/row:opacity-100"
        />
      </Button>
    </li>
  )
}
