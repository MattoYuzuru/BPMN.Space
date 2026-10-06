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
import { emitOnboardingSignal } from '@/shared/lib/onboarding-signals'
import { TOUR_ANCHORS, tourAnchor } from '@/shared/lib/tour-anchors'
import { Button, Card, FlowLine, Icon, IconButton, Stepper, toast } from '@/shared/ui'
import { SummaryChips } from './summary-chips'
import { SUMMARY_VISIBLE_MS, useRunPresentation } from './use-run-presentation'

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
  const cancel = useMutation({
    mutationFn: cancelRun,
    onError: () => toast.error('Не удалось отменить общий прогон'),
  })

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
          <PresentedRun
            view={view}
            onCancel={() => cancel.mutate(view.runId)}
            canCancel={canCancel}
            cancelling={cancel.isPending}
          />
        </m.div>
      )}
    </AnimatePresence>
  )
}

function PresentedRun({
  view,
  ...props
}: {
  view: RunView
  onCancel: () => void
  canCancel: boolean
  cancelling: boolean
}) {
  const presented = useRunStore((state) => state.presented[view.projectId] === view.runId)
  const { displayView, presenting, summaryShown } = useRunPresentation(view, !presented)
  const finishPresentation = useRunStore((state) => state.finishPresentation)
  const setExpanded = useRunStore((state) => state.setExpanded)

  const close = () => {
    // Устаревший таймер не может свернуть карточку нового прогона.
    if (useRunStore.getState().views[view.projectId]?.runId !== view.runId) return
    finishPresentation(view.projectId, view.runId)
    setExpanded(view.projectId, false)
    emitOnboardingSignal({ type: 'run.presented', runId: view.runId, projectId: view.projectId })
  }

  useEffect(() => {
    if (!summaryShown) return
    const timer = setTimeout(() => {
      if (useRunStore.getState().views[view.projectId]?.runId !== view.runId) return
      finishPresentation(view.projectId, view.runId)
      setExpanded(view.projectId, false)
      emitOnboardingSignal({ type: 'run.presented', runId: view.runId, projectId: view.projectId })
    }, SUMMARY_VISIBLE_MS)
    return () => clearTimeout(timer)
  }, [summaryShown, view.projectId, view.runId, finishPresentation, setExpanded])

  return (
    <RunCard
      {...props}
      view={displayView}
      actualView={view}
      presenting={presenting}
      onClose={close}
    />
  )
}

function RunCard({
  view,
  actualView,
  presenting,
  onClose,
  onCancel,
  canCancel,
  cancelling,
}: {
  view: RunView
  actualView: RunView
  presenting: boolean
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
  const elapsed = Math.max(0, (actualView.finishedAt ?? clock) - actualView.startedAt)
  const showingCompletedStages = presenting && actualView.status === 'succeeded'
  return (
    <Card
      variant="elevated"
      padding="none"
      glow={running && !showingCompletedStages}
      role="status"
      aria-live="polite"
      aria-label={`Ход прогона: ${labels.title}`}
      {...tourAnchor(TOUR_ANCHORS.runProgress)}
      className="overflow-hidden bg-surface-raised shadow-lg"
    >
      <FlowLine
        state={
          cancelled || failed
            ? 'idle'
            : showingCompletedStages
              ? 'done'
              : running
                ? 'active'
                : 'done'
        }
        className="absolute inset-x-0 top-0"
      />
      <div className="flex items-center gap-2 px-4 pt-3.5 pb-3">
        <span
          className={
            cancelled
              ? 'grid size-6 place-items-center rounded-md bg-surface text-fg-muted'
              : failed
                ? 'grid size-6 place-items-center rounded-md bg-danger-subtle text-danger-fg'
                : running
                  ? 'grid size-6 place-items-center rounded-md bg-accent-subtle text-accent-fg'
                  : 'grid size-6 place-items-center rounded-md bg-success-subtle text-success-fg'
          }
        >
          <Icon
            name={cancelled ? 'x' : failed ? 'alert-circle' : running ? 'bolt' : 'circle-check'}
            size={14}
          />
        </span>
        <div className="flex min-w-0 flex-1 flex-col">
          <span className="type-subheading text-fg">
            {cancelled
              ? 'Прогон отменён'
              : failed
                ? 'Прогон остановлен'
                : running
                  ? showingCompletedStages
                    ? 'Результат готов'
                    : labels.title
                  : labels.done}
          </span>
          <span className="type-caption text-fg-subtle" data-numeric role="timer" aria-live="off">
            {actualView.status === 'running'
              ? `Прошло ${formatDuration(elapsed)}`
              : elapsed < 1000
                ? 'менее 1 с'
                : formatDuration(elapsed)}
          </span>
        </div>
        {actualView.status === 'running' && canCancel && (
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
        {actualView.status !== 'running' && (
          <IconButton icon="x" size="sm" label="Скрыть" onClick={onClose} />
        )}
      </div>
      <div className="px-4 pb-4">
        {running || failed ? (
          <>
            <Stepper aria-label="Этапы прогона" steps={runSteps(view)} />
            {actualView.status === 'running' && <RunHint stage={view.stage} />}
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
