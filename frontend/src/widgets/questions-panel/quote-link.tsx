import type { Quote, Source } from '@/entities/source'
import { SOURCE_KIND } from '@/entities/source'
import { cn } from '@/shared/lib/cn'
import { Icon } from '@/shared/ui'
import { useWorkspace } from '@/widgets/workspace/model'

/**
 * Цитата из источника со ссылкой на него: клик открывает источник с подсвеченным фрагментом.
 * `evidence` — доказательство решения (Хвоя), `about` — повод для вопроса (нейтрально).
 */
export function QuoteLink({
  quote,
  source,
  tone = 'about',
  clamp = true,
}: {
  quote: Quote
  source?: Source
  tone?: 'about' | 'evidence'
  clamp?: boolean
}) {
  const { openSource } = useWorkspace()
  return (
    <a
      href={`?source=${quote.source_id}`}
      onClick={(event) => {
        event.preventDefault()
        openSource(quote.source_id, quote.quote)
      }}
      className={cn(
        'group/quote flex flex-col gap-1 rounded-md border-l-2 py-1 pr-2 pl-3 outline-none transition-colors duration-base ease-soft',
        'focus-visible:ring-2 focus-visible:ring-focus-ring',
        tone === 'evidence'
          ? 'border-success/60 bg-success-subtle/50 hover:bg-success-subtle'
          : 'border-border-strong hover:bg-hover',
      )}
    >
      <span className={cn('type-ui text-fg-muted', clamp && 'line-clamp-3')}>«{quote.quote}»</span>
      {source && (
        <span
          className={cn(
            'flex items-center gap-1 type-caption transition-colors duration-base',
            tone === 'evidence'
              ? 'text-success-fg'
              : 'text-fg-subtle group-hover/quote:text-fg-muted',
          )}
        >
          <Icon
            name={tone === 'evidence' ? 'circle-check' : SOURCE_KIND[source.kind].icon}
            size={14}
          />
          <span className="truncate">{source.title}</span>
          <Icon
            name="arrow-up-right"
            size={14}
            className="opacity-0 transition-opacity duration-base group-hover/quote:opacity-100"
          />
        </span>
      )}
    </a>
  )
}
