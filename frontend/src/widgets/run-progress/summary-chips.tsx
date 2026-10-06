import type { QuestionsSummary } from '@/entities/question'
import { cn } from '@/shared/lib/cn'
import { Icon, type IconName, Tooltip } from '@/shared/ui'

const ITEMS: {
  key: 'resolved' | 'open' | 'new'
  label: string
  hint: string
  icon: IconName
  tone: string
}[] = [
  {
    key: 'resolved',
    label: 'Решено',
    hint: 'Вопросы, закрытые цитатой из источника',
    icon: 'circle-check',
    tone: 'text-success',
  },
  {
    key: 'open',
    label: 'Осталось',
    hint: 'Открытые вопросы с прошлых прогонов',
    icon: 'circle-dashed',
    tone: 'text-fg-subtle',
  },
  {
    key: 'new',
    label: 'Новых',
    hint: 'Вопросы, которые задал последний прогон',
    icon: 'sparkles',
    tone: 'text-amber',
  },
]

/**
 * Плашка итогов вопросов: «Решено N | Осталось N | Новых N». Части разделены тонкими линиями,
 * у каждой — иконка смысла и подсказка. Изменившееся число коротко вспыхивает.
 */
export function SummaryChips({
  summary,
  size = 'md',
  className,
}: {
  summary: Pick<QuestionsSummary, 'resolved' | 'open' | 'new'>
  size?: 'sm' | 'md'
  className?: string
}) {
  return (
    <dl
      aria-label="Итоги вопросов"
      className={cn(
        'items-stretch rounded-md border border-border bg-surface',
        size === 'sm' ? 'inline-flex h-7' : '@container grid min-h-8 w-full grid-cols-3',
        className,
      )}
    >
      {ITEMS.map((item, index) => (
        <Tooltip key={item.key} content={item.hint} side="bottom">
          <div
            className={cn(
              'flex min-w-0 items-center justify-center type-caption text-fg-muted',
              size === 'sm'
                ? 'gap-1.5 px-2.5'
                : 'flex-col gap-0.5 px-2 py-1 @[24rem]:flex-row @[24rem]:gap-1.5',
              index > 0 && 'border-l border-border',
            )}
          >
            <dt className="flex min-w-0 items-center gap-1.5 whitespace-nowrap">
              <Icon
                name={item.icon}
                size={14}
                className={cn('shrink-0', item.tone, size === 'md' && 'hidden @[17rem]:block')}
              />
              {item.label}
            </dt>
            <dd
              key={summary[item.key]}
              data-numeric
              className="shrink-0 font-medium text-fg animate-pop-in"
            >
              {summary[item.key]}
            </dd>
          </div>
        </Tooltip>
      ))}
    </dl>
  )
}
