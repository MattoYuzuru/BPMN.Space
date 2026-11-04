import { useMutation } from '@tanstack/react-query'
import { AnimatePresence, m } from 'motion/react'
import { useEffect, useState } from 'react'
import {
  agentSteps,
  cancelRun,
  isAgentRun,
  RUN_MODE_LABEL,
  type RunCost,
  type RunView,
  runSteps,
  useResumeRun,
  useRunStore,
  useRunView,
} from '@/entities/run'
import { formatDuration, formatMoney, formatTokens } from '@/shared/lib/format'
import { floatingPanel } from '@/shared/lib/motion'
import { emitOnboardingSignal } from '@/shared/lib/onboarding-signals'
import { TOUR_ANCHORS, tourAnchor } from '@/shared/lib/tour-anchors'
import {
  Badge,
  Button,
  Card,
  CostMeter,
  Divider,
  FlowLine,
  Icon,
  IconButton,
  Stepper,
  toast,
} from '@/shared/ui'
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
  const waiting = actualView.status === 'waiting'
  const running = !waiting && view.status === 'running'
  const failed = view.status === 'failed'
  const cancelled = view.status === 'cancelled'
  const resume = useResumeRun(actualView.projectId)
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
          cancelled || failed || waiting
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
            waiting
              ? 'grid size-6 place-items-center rounded-md bg-amber-subtle text-amber-fg'
              : cancelled
                ? 'grid size-6 place-items-center rounded-md bg-surface text-fg-muted'
                : failed
                  ? 'grid size-6 place-items-center rounded-md bg-danger-subtle text-danger-fg'
                  : running
                    ? 'grid size-6 place-items-center rounded-md bg-accent-subtle text-accent-fg'
                    : 'grid size-6 place-items-center rounded-md bg-success-subtle text-success-fg'
          }
        >
          <Icon
            name={
              waiting
                ? 'clock'
                : cancelled
                  ? 'x'
                  : failed
                    ? 'alert-circle'
                    : running
                      ? 'bolt'
                      : 'circle-check'
            }
            size={14}
          />
        </span>
        <div className="flex min-w-0 flex-1 flex-col">
          <span className="flex flex-wrap items-center gap-1.5 type-subheading text-fg">
            {waiting
              ? 'Ждёт вашего действия'
              : cancelled
                ? 'Прогон отменён'
                : failed
                  ? 'Прогон остановлен'
                  : running
                    ? showingCompletedStages
                      ? 'Результат готов'
                      : labels.title
                    : labels.done}
            {isAgentRun(view) && (
              <Badge tone="accent" variant="outline" icon="bolt">
                Агентный режим
              </Badge>
            )}
          </span>
          <span className="type-caption text-fg-subtle" data-numeric role="timer" aria-live="off">
            {waiting
              ? 'Ответьте на технический вопрос'
              : actualView.status === 'running'
                ? `Прошло ${formatDuration(elapsed)}`
                : elapsed < 1000
                  ? 'менее 1 с'
                  : formatDuration(elapsed)}
          </span>
        </div>
        {waiting && canCancel && (
          <Button
            size="sm"
            variant="primary"
            loading={resume.isPending}
            onClick={() => resume.mutate(actualView.runId)}
          >
            Продолжить
          </Button>
        )}
        {(actualView.status === 'running' || waiting) && canCancel && (
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
        {(actualView.status === 'succeeded' ||
          actualView.status === 'failed' ||
          actualView.status === 'cancelled') && (
          <IconButton icon="x" size="sm" label="Скрыть" onClick={onClose} />
        )}
      </div>
      <div className="px-4 pb-4">
        {waiting ? (
          <div
            className="flex items-start gap-2 rounded-md bg-amber-subtle px-3 py-2.5 type-caption text-amber-fg"
            role="status"
          >
            <Icon name="alert-triangle" size={14} className="mt-0.5 shrink-0" />
            <span>
              Прогон остановился на техническом вопросе. Ответьте на него в панели вопросов или
              продолжите без него: работа начнётся заново с первого этапа, потраченное останется.
            </span>
          </div>
        ) : running || failed ? (
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
        {isAgentRun(view) && (
          <div
            className="mt-3 flex flex-wrap items-center gap-x-2 gap-y-1 type-caption text-fg-muted"
            data-testid="run-agent-steps"
            data-numeric
          >
            <Icon name="bolt" size={14} className="text-accent-fg" />
            <span>
              Ходов агента: {agentSteps(actualView.cost)}
              {view.maxSteps ? ` из ${view.maxSteps}` : ''}
            </span>
            <span className="text-fg-subtle">
              Инструменты и журнал ходов сервер в прогон не отдаёт — здесь реальные вызовы модели.
            </span>
          </div>
        )}
        <RunCostBlock cost={actualView.cost} budgetUsd={actualView.budget?.cost_usd ?? null} />
      </div>
    </Card>
  )
}

/** Стоимость прогона и разбивка по этапам (RFC-0005): обновляется потоком `usage`. */
function RunCostBlock({ cost, budgetUsd }: { cost: RunCost | null; budgetUsd: number | null }) {
  const spent = cost?.cost_usd ?? null
  if (!cost && budgetUsd === null) return null
  const hasMoney = spent !== null || budgetUsd !== null
  return (
    <div
      className="mt-3 border-t border-border pt-3"
      {...tourAnchor(TOUR_ANCHORS.runCost)}
      data-testid="run-cost"
    >
      {hasMoney ? (
        <CostMeter
          size="sm"
          label="Стоимость"
          spent={spent}
          budget={budgetUsd}
          incomplete={cost ? !cost.complete : false}
          incompleteNote="Стоимость известна не полностью: у части шагов нет цен. Это не ошибка прогона."
        />
      ) : (
        <p className="flex items-center gap-1 type-caption text-amber-fg">
          <Icon name="alert-triangle" size={14} />
          Цены модели неизвестны: стоимость в деньгах не рассчитана
        </p>
      )}
      {cost && (
        <span className="mt-1 block type-caption text-fg-subtle" data-numeric>
          {formatTokens(cost.tokens_in + cost.tokens_out)} токенов{' \u00B7 '}
          {cost.calls === 1 ? '1 вызов' : `${cost.calls} вызовов`}
          {cost.cache_read_tokens > 0 &&
            ` \u00B7 кеш ${formatTokens(cost.cache_read_tokens)} прочитано`}
        </span>
      )}
      {cost && (cost.by_stage?.length ?? 0) > 0 && (
        <details className="group mt-2">
          <summary className="cursor-pointer list-none type-caption text-fg-muted outline-none hover:text-fg focus-visible:ring-2 focus-visible:ring-focus-ring">
            По этапам
          </summary>
          <Divider className="my-2" />
          <ul aria-label="Стоимость по этапам" className="flex flex-col gap-1">
            {(cost.by_stage ?? []).map((stage) => (
              <li key={stage.stage} className="flex items-baseline justify-between gap-3">
                <span className="min-w-0 truncate type-caption text-fg-muted">{stage.label}</span>
                <span className="shrink-0 type-caption text-fg-subtle" data-numeric>
                  {stage.cost_usd !== null && stage.cost_usd !== undefined
                    ? formatMoney(stage.cost_usd)
                    : 'цена неизвестна'}
                </span>
              </li>
            ))}
          </ul>
        </details>
      )}
    </div>
  )
}

function RunHint({ stage }: { stage: RunView['stage'] }) {
  const hint =
    stage === 'extracting'
      ? 'Модель анализирует источники и проверяет вопросы. Это может занять несколько минут.'
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
