import { AnimatePresence, m } from 'motion/react'
import { useEffect, useState } from 'react'
import { RUN_MODE_LABEL, type RunView, runSteps, useRunStore, useRunView } from '@/entities/run'
import { formatDuration } from '@/shared/lib/format'
import { floatingPanel } from '@/shared/lib/motion'
import { Card, FlowLine, Icon, IconButton, Stepper } from '@/shared/ui'
import { SummaryChips } from './summary-chips'

/** Сколько итог прогона остаётся на экране после завершения. */
const SUMMARY_VISIBLE_MS = 6000

/**
 * Ход прогона: плавающая карточка над схемой со Stepper этапов из SSE и линией тока.
 * После завершения показывает итог (решено, осталось, новые) и сворачивается сама.
 */
export function RunProgress({ projectId }: { projectId: string }) {
  const view = useRunView(projectId)
  const expanded = useRunStore((state) => state.expanded[projectId] ?? false)
  const setExpanded = useRunStore((state) => state.setExpanded)
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
          <RunCard view={view} onClose={() => setExpanded(projectId, false)} />
        </m.div>
      )}
    </AnimatePresence>
  )
}

function RunCard({ view, onClose }: { view: RunView; onClose: () => void }) {
  const [clock, setClock] = useState(Date.now())
  const labels = RUN_MODE_LABEL[view.mode]
  const running = view.status === 'running'
  const failed = view.status === 'failed'
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
            {failed ? 'Прогон остановлен' : running ? labels.title : labels.done}
          </span>
          <span className="type-caption text-fg-subtle" data-numeric role="timer" aria-live="off">
            {running ? `Прошло ${formatDuration(elapsed)}` : formatDuration(elapsed)}
          </span>
        </div>
        <IconButton icon="x" size="sm" label="Скрыть" onClick={onClose} />
      </div>
      <div className="px-4 pb-4">
        {running || failed ? (
          <>
            <Stepper aria-label="Этапы прогона" steps={runSteps(view)} />
            {running && <RunHint stage={view.stage} />}
          </>
        ) : (
          <div className="flex flex-col gap-3 animate-fade-in">
            {view.summary && <SummaryChips summary={view.summary} />}
            {view.mode === 'build' && (
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
