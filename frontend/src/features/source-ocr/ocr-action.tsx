import { remainingOcrPages, type Source, useRetrySourceOcr } from '@/entities/source'
import { formatCount, formatMoney } from '@/shared/lib/format'
import { Badge, Button, Card, Icon, Progress } from '@/shared/ui'

/**
 * Действие «Распознать страницы» для PDF со сканами (волна 3). Показывает состояние узла OCR:
 * не запускали, распознаётся, остались непрочитанные страницы, ошибка; повтор не платит заново
 * за готовые страницы.
 */
export function SourceOcrAction({
  source,
  projectId,
  canEdit,
  nodes,
}: {
  source: Source
  projectId: string
  canEdit: boolean
  /** Производные узлы источника: среди них может быть узел OCR. */
  nodes: readonly Source[]
}) {
  const retry = useRetrySourceOcr(projectId)
  const pages = source.unreadable_pages ?? []
  const ocr = nodes.find((node) => node.derivation?.capability === 'ocr') ?? null
  if (pages.length === 0 && !ocr) return null
  const ocrRemaining = ocr ? remainingOcrPages(ocr) : []
  const done = ocr?.status === 'ready' && ocrRemaining.length === 0
  const remaining = done ? [] : ocrRemaining.length > 0 ? ocrRemaining : pages
  const processing = ocr?.status === 'processing'
  const failed = ocr?.status === 'failed'
  const cost = ocr?.derivation?.cost_usd ?? null
  return (
    <Card variant="sunken" padding="sm" className="flex flex-col gap-2">
      <div className="flex flex-wrap items-center gap-2">
        <Icon name="file-text" size={16} className="shrink-0 text-fg-subtle" />
        <span className="type-ui text-fg">
          {processing
            ? 'Распознаю текст страниц'
            : remaining.length > 0
              ? `${formatCount(remaining.length, ['страница', 'страницы', 'страниц'])} без текста`
              : 'Страницы распознаны'}
        </span>
        {ocr?.derivation?.provider && (
          <Badge tone="neutral" variant="outline">
            {ocr.derivation.provider}
          </Badge>
        )}
        {cost !== null && cost > 0 && (
          <span className="type-caption text-fg-subtle" data-numeric>
            {formatMoney(cost)}
          </span>
        )}
      </div>
      {processing && <Progress label="Распознавание страниц" />}
      {failed && (
        <p role="alert" className="type-caption text-danger-fg">
          {ocr?.error ?? 'Распознавание не удалось'}
        </p>
      )}
      {!processing && remaining.length > 0 && (
        <p className="type-caption text-fg-muted">
          Это сканы без текстового слоя. OCR прочитает страницы моделью; готовые страницы повторно
          не оплачиваются.
        </p>
      )}
      {processing && (
        <p className="type-caption text-fg-muted">
          Готовые страницы сохранятся: можно закрыть лист и вернуться позже.
        </p>
      )}
      {canEdit && !processing && remaining.length > 0 && (
        <Button
          size="sm"
          variant="secondary"
          leadingIcon="refresh"
          loading={retry.isPending}
          onClick={() => retry.mutate(source.id)}
        >
          {ocr ? 'Повторить распознавание' : 'Распознать страницы'}
        </Button>
      )}
    </Card>
  )
}
