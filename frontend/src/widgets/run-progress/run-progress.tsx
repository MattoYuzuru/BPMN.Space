import { useMutation } from '@tanstack/react-query'
import { AnimatePresence, m } from 'motion/react'
import { useEffect, useState } from 'react'
import {
  cancelRun,
  RUN_MODE_LABEL,
  type RunView,
  runSteps,
  useRunStore,
  useRunView,
} from '@/entities/run'
import { formatDuration } from '@/shared/lib/format'
import { floatingPanel } from '@/shared/lib/motion'
import { TOUR_ANCHORS, tourAnchor } from '@/shared/lib/tour-anchors'
import { Button, Card, FlowLine, Icon, IconButton, Stepper, toast } from '@/shared/ui'
import { SummaryChips } from './summary-chips'

/** Сколько итог прогона остаётся на экране после завершения. */
const SUMMARY_VISIBLE_MS = 6000

/**
 * Ход прогона: плавающая карточка над схемой со Stepper этапов из SSE и линией тока.
 * После завершения показывает итог (решено, осталось, новые) и сворачивается сама.
 */
export function RunProgress({
  projectId,
  canCancel = true,
}: {
  projectId: string
  canCancel?: boolean
}) {
  const view = useRunView(projectId)
  const expanded = useRunStore((state) => state.expanded[projectId] ?? false)
  const setExpanded = useRunStore((state) => state.setExpanded)
  const cancel = useMutation({
    mutationFn: cancelRun,
    onError: () => toast.error('Не удалось отменить общий прогон'),
  })
  const finished = view && view.status !== 'running'

  useEffect(() => {
    if (!finished || view?.status === 'failed') return
    const timer = setTimeout(() => setExpanded(projectId, false), SUMMARY_VISIBLE_MS)
    return () => clearTimeout(timer)
  }, [finished, view?.status, projectId, setExpanded])

  return (
    <AnimatePresence mode="wait">
      {view && expanded && (
        <m.div
          key={view.runId}
          variants={floatingPanel}
          initial="initial"
          animate="animate"
          exit="exit"
          className="pointer-events-auto w-80"
        >
          <RunCard
            view={view}
            onClose={() => setExpanded(projectId, false)}
            onCancel={() => cancel.mutate(view.runId)}
            canCancel={canCancel}
            cancelling={cancel.isPending}
          />
        </m.div>
      )}
    </AnimatePresence>
  )
}

function RunCard({
  view,
  onClose,
  onCancel,
  canCancel,
  cancelling,
}: {
  view: RunView
  onClose: () => void
  onCancel: () => void
  canCancel: boolean
  cancelling: boolean
}) {
  const [clock, setClock] = useState(Date.now())
  const labels = RUN_MODE_LABEL[view.mode]
  const running = view.status === 'running'
  const failed = view.status === 'failed'
  const cancelled = view.status === 'cancelled'
  useEffect(() => {
    if (!running) return
    const timer = window.setInterval(() => setClock(Date.now()), 1000)
    return () => window.clearInterval(timer)
  }, [running])
  const elapsed = Math.max(0, (view.finishedAt ?? clock) - view.startedAt)
  return (
    <Card
      variant="elevated"
      padding="none"
      glow={running}
      role="status"
      aria-live="polite"
      aria-label={`Ход прогона: ${labels.title}`}
      {...tourAnchor(TOUR_ANCHORS.runProgress)}
      className="overflow-hidden bg-surface-raised shadow-lg"
    >
      <FlowLine
        state={running ? 'active' : failed ? 'idle' : 'done'}
        className="absolute inset-x-0 top-0"
      />
      <div className="flex items-center gap-2 px-4 pt-3.5 pb-3">
        <span
          className={
            failed
              ? 'grid size-6 place-items-center rounded-md bg-danger-subtle text-danger-fg'
              : running
                ? 'grid size-6 place-items-center rounded-md bg-accent-subtle text-accent-fg'
                : 'grid size-6 place-items-center rounded-md bg-success-subtle text-success-fg'
          }
        >
          <Icon name={failed ? 'alert-circle' : running ? 'bolt' : 'circle-check'} size={14} />
        </span>
        <div className="flex min-w-0 flex-1 flex-col">
          <span className="type-subheading text-fg">
            {cancelled
              ? 'Прогон отменён'
              : failed
                ? 'Прогон остановлен'
                : running
                  ? labels.title
                  : labels.done}
          </span>
          <span className="type-caption text-fg-subtle" data-numeric role="timer" aria-live="off">
            {running ? `Прошло ${formatDuration(elapsed)}` : formatDuration(elapsed)}
          </span>
        </div>
        {running && canCancel && (
          <Button
            size="sm"
            variant="ghost"
            className="text-danger-fg"
            onClick={onCancel}
            disabled={cancelling}
            loading={cancelling}
          >
            {cancelling ? 'Отменяю…' : 'Отменить прогон'}
          </Button>
        )}
        {!running && <IconButton icon="x" size="sm" label="Скрыть" onClick={onClose} />}
      </div>
      <div className="px-4 pb-4">
        {running || failed ? (
          <>
            <Stepper aria-label="Этапы прогона" steps={runSteps(view)} />
            {running && <RunHint stage={view.stage} />}
          </>
        ) : (
          <div className="flex flex-col gap-3 animate-fade-in">
            {cancelled && (
              <p className="type-caption text-fg-muted">Остановлено участником проекта.</p>
            )}
            {view.summary && <SummaryChips summary={view.summary} />}
            <RunWarnings warnings={view.warnings} />
            {!cancelled && view.mode === 'build' && (
              <span className="flex items-center gap-1.5 type-caption text-fg-muted">
                <Icon name="diagram" size={14} />
                Новая версия схемы уже на холсте
              </span>
            )}
          </div>
        )}
      </div>
    </Card>
  )
}

function RunHint({ stage }: { stage: RunView['stage'] }) {
  const hint =
    stage === 'extracting'
      ? 'Модель анализирует источники. Это может занять до двух минут.'
      : stage === 'structuring'
        ? 'Модель собирает шаги процесса в структуру диаграммы.'
        : null
  if (!hint) return null
  return <p className="mt-3 border-t border-border pt-3 type-caption text-fg-muted">{hint}</p>
}

/** Спокойное предупреждение: прогон удался, но часть материалов учтена не полностью. */
function RunWarnings({ warnings }: { warnings: readonly string[] }) {
  if (warnings.length === 0) return null
  return (
    <div
      role="note"
      aria-label="Предупреждения прогона"
      className="flex flex-col gap-1.5 rounded-md bg-amber-subtle px-3 py-2.5"
    >
      <span className="flex items-center gap-1.5 type-caption font-medium text-amber-fg">
        <Icon name="alert-triangle" size={14} className="text-amber" />
        Учтено не всё
      </span>
      <ul className="flex flex-col gap-1 type-caption text-amber-fg">
        {warnings.map((warning) => (
          <li key={warning}>{warning}</li>
        ))}
      </ul>
    </div>
  )
}
