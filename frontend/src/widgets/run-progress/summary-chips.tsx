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
    <div
      className={cn(
        'inline-flex items-stretch rounded-md border border-border bg-surface',
        size === 'sm' ? 'h-7' : 'h-8',
        className,
      )}
    >
      {ITEMS.map((item, index) => (
        <Tooltip key={item.key} content={item.hint} side="bottom">
          <span
            className={cn(
              'flex items-center gap-1.5 px-2.5 type-caption text-fg-muted',
              index > 0 && 'border-l border-border',
            )}
          >
            <Icon name={item.icon} size={14} className={item.tone} />
            {item.label}
            <span
              key={summary[item.key]}
              data-numeric
              className="font-medium text-fg animate-pop-in"
            >
              {summary[item.key]}
            </span>
          </span>
        </Tooltip>
      ))}
    </div>
  )
}
