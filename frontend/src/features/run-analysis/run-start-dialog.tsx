import { useEffect, useMemo, useState } from 'react'
import {
  effectiveEffort,
  effortOptions,
  getModelChoice,
  type ModelCapabilities,
  resolveChoice,
  useLlmCredentials,
  useLlmModels,
  useModelChoiceStore,
} from '@/entities/llm-credential'
import {
  AGENT_STEP_PRESETS,
  DEFAULT_AGENT_MAX_STEPS,
  estimateCallsText,
  estimateCost,
  estimateCurrency,
  estimateDurationText,
  estimateIncomplete,
  estimateTokensText,
  RUN_MODE_LABEL,
  type RunBudget,
  type RunMode,
  type RunProfileMode,
  useRunEstimate,
  useStartRun,
} from '@/entities/run'
import { useCurrentUser } from '@/entities/session'
import { ModelPicker } from '@/features/model-picker/model-picker'
import { AgentModeHint } from '@/features/onboarding/agent-mode-hint'
import { ApiError, errorMessage } from '@/shared/api/client'
import { cn } from '@/shared/lib/cn'
import { formatDate, formatMoneyRange, formatNumberRange } from '@/shared/lib/format'
import { parseMoneyInput, parseTokensInput } from '@/shared/lib/number-input'
import { TOUR_ANCHORS, tourAnchor } from '@/shared/lib/tour-anchors'
import {
  Badge,
  Button,
  Card,
  CostMeter,
  Dialog,
  DialogContent,
  Divider,
  Field,
  Icon,
  Input,
  SegmentedControl,
  Skeleton,
  Tag,
} from '@/shared/ui'

export interface RunStartDialogProps {
  projectId: string
  /** Начальный режим: «Анализ» или «Сборка схемы». */
  mode: RunMode
  open: boolean
  onOpenChange: (open: boolean) => void
}

interface BudgetFields {
  cost: string
  tokens: string
}

const EMPTY_BUDGET: BudgetFields = { cost: '', tokens: '' }

/** «Лимит шагов»: целое 1–200; иначе — понятная ошибка, а не молчаливое обрезание. */
export function parseAgentSteps(value: string): number | null {
  const trimmed = value.trim()
  if (!/^\d+$/.test(trimmed)) return null
  const steps = Number.parseInt(trimmed, 10)
  return steps >= 1 && steps <= 200 ? steps : null
}

export interface ParsedBudget {
  budget: RunBudget | null
  costError: string | null
  tokensError: string | null
  valid: boolean
}

/**
 * Бюджет из полей формы: пустые поля — без ограничения, мусор — ошибка поля,
 * а не молча обрезанное число. «100 000» и «1 000,50» понимаются как есть.
 */
export function parseBudgetFields(fields: BudgetFields): ParsedBudget {
  const cost = parseMoneyInput(fields.cost)
  const tokens = parseTokensInput(fields.tokens)
  const budget: RunBudget = {
    cost_usd: cost.value,
    tokens: tokens.value,
  }
  return {
    budget: budget.cost_usd === null && budget.tokens === null ? null : budget,
    costError: cost.error,
    tokensError: tokens.error,
    valid: !cost.error && !tokens.error,
  }
}

/** Оценка должна пересчитаться после смены профиля, но не на каждый введённый знак. */
export const ESTIMATE_DEBOUNCE_MS = 350

/**
 * Запуск прогона с оценкой стоимости (RFC-0005, шаги 4–5): режим, модель и глубина работы,
 * бюджет в деньгах и токенах, диапазон цены и времени, разбивка по этапам.
 * Запуск передаёт бюджет в `RunCreate.profile.budget`.
 */
export function RunStartDialog({
  projectId,
  mode: initialMode,
  open,
  onOpenChange,
}: RunStartDialogProps) {
  const user = useCurrentUser()
  const credentials = useLlmCredentials(Boolean(user))
  const choices = useModelChoiceStore((state) => state.choices)
  const items = credentials.data?.items ?? []
  const stored = user ? (choices[user.id] ?? getModelChoice(user.id)) : null
  const choice = useMemo(
    () => (stored && items.some((item) => item.id === stored.credentialId) ? stored : null),
    [stored, items],
  )
  const resolved = useMemo(() => resolveChoice(items, choice), [items, choice])
  const models = useLlmModels(resolved?.credential.id, { background: true })
  const capabilities = capabilitiesOf(models.data, resolved?.model)
  const levels = effortOptions(capabilities)
  const effort = effectiveEffort(choice?.effort, capabilities)

  const [mode, setMode] = useState<RunMode>(initialMode)
  const [fields, setFields] = useState<BudgetFields>(EMPTY_BUDGET)
  const [profileMode, setProfileMode] = useState<RunProfileMode>('pipeline')
  const [steps, setSteps] = useState(String(DEFAULT_AGENT_MAX_STEPS))
  const maxSteps = parseAgentSteps(steps)
  // Сервер не отдаёт LLM_AGENT_MODE: правду узнаём из оценка/запуска (422). Блокируем только
  // явно неподходящую выбранную модель; без своего ключа возможен операторский ключ сервера.
  const modelBlocksAgent = Boolean(resolved && capabilities && capabilities.tools === false)
  const agentReason = modelBlocksAgent
    ? 'Эта модель не поддерживает инструменты, поэтому агентный режим недоступен. Выберите другую модель.'
    : !resolved
      ? 'Без своего ключа сервер возьмёт модель оператора: режим доступен, если она умеет инструменты. Сервер проверит при запуске.'
      : capabilities === undefined
        ? 'Возможности модели ещё загружаются — сервер проверит режим при запуске.'
        : null
  const canUseAgent = !modelBlocksAgent
  const parsedBudget = useMemo(() => parseBudgetFields(fields), [fields])
  const budget = parsedBudget.budget
  const estimate = useRunEstimate(projectId)
  const start = useStartRun(projectId)

  // Режим приходит из той кнопки, которой открыли диалог.
  useEffect(() => {
    if (open) setMode(initialMode)
  }, [open, initialMode])

  // Новый диалог — чистое поле бюджета и без старых ошибок прошлого запуска/оценки.
  // biome-ignore lint/correctness/useExhaustiveDependencies: сброс только в момент открытия
  useEffect(() => {
    if (!open) return
    setFields(EMPTY_BUDGET)
    setProfileMode('pipeline')
    setSteps(String(DEFAULT_AGENT_MAX_STEPS))
    start.reset()
    estimate.reset()
  }, [open])

  // Агентный режим недоступен — возвращаемся к конвейеру, объяснение уже под переключателем.
  useEffect(() => {
    if (!open || canUseAgent || profileMode === 'pipeline') return
    setProfileMode('pipeline')
  }, [open, canUseAgent, profileMode])

  const request = useMemo(
    () => ({
      mode,
      ...(resolved ? { credential_id: resolved.credential.id, model: resolved.model } : {}),
      profile: {
        ...(effort ? { effort } : {}),
        ...(budget ? { budget } : {}),
        mode: profileMode,
        ...(profileMode === 'agent' && maxSteps ? { max_steps: maxSteps } : {}),
      },
    }),
    [mode, resolved, effort, budget, profileMode, maxSteps],
  )

  // Оценка — POST, поэтому запускаем её эффектом на смену профиля, с короткой паузой.
  // Неверный лимит шагов не должен уходить на сервер «без лимита»: ждём исправления поля.
  useEffect(() => {
    if (!open || (profileMode === 'agent' && maxSteps === null)) return
    const timer = window.setTimeout(() => estimate.mutate(request), ESTIMATE_DEBOUNCE_MS)
    return () => window.clearTimeout(timer)
  }, [open, request, estimate.mutate, profileMode, maxSteps])

  const agentMode = profileMode === 'agent'
  const stepsInvalid = agentMode && maxSteps === null
  const startError =
    start.error instanceof ApiError
      ? { status: start.error.status, message: errorMessage(start.error) }
      : start.error
        ? { status: 0, message: errorMessage(start.error) }
        : null
  const agentRejection =
    startError !== null &&
    agentMode &&
    startError.status === 422 &&
    /agent|агент|LLM_AGENT|инструмент/i.test(startError.message)
  const submit = () => {
    if (!parsedBudget.valid) return
    start.mutate(
      {
        mode,
        budget,
        agentMode,
        ...(agentMode ? { maxSteps } : { maxSteps: null }),
      },
      { onSuccess: () => onOpenChange(false) },
    )
  }

  const labels = RUN_MODE_LABEL[mode]
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        size="lg"
        title={labels.title === 'Анализ' ? 'Анализ проекта' : 'Сборка схемы'}
        description="Оценка до запуска: сколько запросов, времени и денег потребуется. Бюджет можно не задавать."
        footer={
          <>
            <Button variant="ghost" onClick={() => onOpenChange(false)}>
              Отмена
            </Button>
            <Button
              variant="primary"
              leadingIcon={mode === 'build' ? 'diagram' : 'sparkles'}
              loading={start.isPending}
              disabled={stepsInvalid || !parsedBudget.valid}
              onClick={submit}
              {...tourAnchor(TOUR_ANCHORS.runStartConfirm)}
            >
              {mode === 'build' ? 'Построить схему' : 'Запустить анализ'}
            </Button>
          </>
        }
      >
        <div className="flex flex-col gap-5">
          <SegmentedControl<RunMode>
            aria-label="Что сделать"
            value={mode}
            onValueChange={setMode}
            options={[
              { value: 'analyze', label: 'Анализ' },
              { value: 'build', label: 'Сборка схемы' },
            ]}
          />

          <Card variant="sunken" padding="sm" className="flex flex-col gap-2.5">
            <span className="type-label text-fg-muted">Модель и глубина работы</span>
            <ModelPicker />
            {levels.length > 0 && effort ? (
              <span className="type-caption text-fg-muted" data-numeric>
                Уровень: {levels.find((item) => item.value === effort)?.label.toLowerCase()}
              </span>
            ) : (
              <span className="type-caption text-fg-muted">
                Модель выбирается в шапке проекта. Без своего ключа глубина — умолчание сервера.
              </span>
            )}
          </Card>

          <div
            className="flex flex-col gap-3"
            {...tourAnchor(TOUR_ANCHORS.runAgent)}
            data-testid="run-agent"
          >
            <div className="flex flex-col gap-1">
              <span className="type-label text-fg">Режим работы</span>
              <span className="type-caption text-fg-muted">
                Конвейер идёт по этапам и дешевле. Агентный — модель сама читает источники
                инструментами, гибче на сложных материалах, но дороже; шаги и бюджет ограничены.
              </span>
            </div>
            <SegmentedControl<RunProfileMode>
              aria-label="Режим работы"
              aria-describedby={agentReason ? 'agent-mode-reason' : undefined}
              value={profileMode}
              onValueChange={setProfileMode}
              options={[
                { value: 'pipeline', label: 'Конвейер', icon: 'route', disabled: false },
                {
                  value: 'agent',
                  label: 'Агентный',
                  icon: 'bolt',
                  disabled: !canUseAgent,
                },
              ]}
            />
            {agentReason && (
              <span id="agent-mode-reason" className="type-caption text-fg-muted">
                {agentReason}
              </span>
            )}
            <AgentModeHint enabled={canUseAgent} />
            {profileMode === 'agent' && (
              <div className="flex flex-col gap-2">
                <div className="flex flex-wrap items-end gap-2">
                  <Field
                    label="Лимит шагов"
                    hint="Ходов агента; не больше серверного потолка"
                    error={stepsInvalid ? 'Введите целое число от 1 до 200' : undefined}
                    className="w-36"
                  >
                    <Input
                      inputMode="numeric"
                      value={steps}
                      placeholder="12"
                      onChange={(event) => setSteps(event.target.value)}
                    />
                  </Field>
                  <div className="flex flex-wrap gap-1">
                    {AGENT_STEP_PRESETS.map((preset) => (
                      <Button
                        key={preset}
                        size="sm"
                        variant={maxSteps === preset ? 'secondary' : 'ghost'}
                        onClick={() => setSteps(String(preset))}
                      >
                        {preset}
                      </Button>
                    ))}
                  </div>
                  <Tag icon="bolt">агент</Tag>
                </div>
                <span className="type-caption text-fg-muted">
                  Достигнутый лимит — мягкая остановка «ждёт вашего действия», как при исчерпанном
                  бюджете: можно поднять шаги или продолжить.
                </span>
              </div>
            )}
            {startError && agentMode && (
              <div
                role="alert"
                className="flex items-start gap-2 rounded-md bg-danger-subtle px-3 py-2.5 type-caption text-danger-fg"
              >
                <Icon name="alert-circle" size={14} className="mt-0.5 shrink-0" />
                <span>
                  {agentRejection
                    ? `Сервер не разрешил агентный режим: ${startError.message} Выберите конвейер или другую модель.`
                    : `Прогон не запущен: ${startError.message}`}
                </span>
              </div>
            )}
          </div>

          <div
            className="flex flex-col gap-3"
            {...tourAnchor(TOUR_ANCHORS.runBudget)}
            data-testid="run-budget"
          >
            <div className="flex flex-col gap-1">
              <span className="type-label text-fg">Бюджет</span>
              <span className="type-caption text-fg-muted">
                Прогон остановится и спросит, что делать, если бюджет закончится.
              </span>
            </div>
            <div className="grid grid-cols-2 gap-3">
              <Field
                label="В долларах"
                optional
                hint="Например, 10"
                error={parsedBudget.costError ?? undefined}
              >
                <Input
                  inputMode="decimal"
                  value={fields.cost}
                  placeholder="Без ограничения"
                  onChange={(event) =>
                    setFields((current) => ({ ...current, cost: event.target.value }))
                  }
                />
              </Field>
              <Field
                label="В токенах"
                optional
                hint="Вход и ответ вместе"
                error={parsedBudget.tokensError ?? undefined}
              >
                <Input
                  inputMode="numeric"
                  value={fields.tokens}
                  placeholder="Без ограничения"
                  onChange={(event) =>
                    setFields((current) => ({ ...current, tokens: event.target.value }))
                  }
                />
              </Field>
            </div>
          </div>

          <div {...tourAnchor(TOUR_ANCHORS.runEstimate)} data-testid="run-estimate">
            <EstimateBlock
              state={estimate}
              budget={budget}
              mode={mode}
              agentMode={agentMode}
              onRetry={() => estimate.mutate(request)}
            />
          </div>
        </div>
      </DialogContent>
    </Dialog>
  )
}

function capabilitiesOf(
  models: { id: string; capabilities: ModelCapabilities }[] | undefined,
  model: string | undefined,
): ModelCapabilities | undefined {
  return model ? models?.find((item) => item.id === model)?.capabilities : undefined
}

/** Блок оценки: диапазон денег, время, запросы, токены и разбивка по этапам. */
function EstimateBlock({
  state,
  budget,
  mode,
  agentMode,
  onRetry,
}: {
  state: ReturnType<typeof useRunEstimate>
  budget: RunBudget | null
  mode: RunMode
  agentMode: boolean
  onRetry: () => void
}) {
  if (state.isPending && !state.data) {
    return (
      <Card variant="sunken" padding="sm" className="flex flex-col gap-3" aria-busy="true">
        <Skeleton className="h-4 w-32" />
        <Skeleton className="h-10 w-full" />
        <Skeleton className="h-4 w-2/3" />
      </Card>
    )
  }
  if (state.isError) {
    const rejection = errorMessage(state.error)
    const agentRejected =
      agentMode &&
      state.error instanceof ApiError &&
      state.error.status === 422 &&
      /agent|агент|LLM_AGENT|инструмент/i.test(rejection)
    return (
      <Card variant="sunken" padding="sm" className="flex items-start gap-2">
        <Icon name="alert-circle" size={16} className="mt-0.5 shrink-0 text-danger-fg" />
        <div className="flex min-w-0 flex-1 flex-col gap-2">
          <p className="type-ui text-danger-fg">
            {agentRejected ? 'Сервер не разрешил агентный режим' : 'Оценку получить не удалось'}
          </p>
          <p className="type-caption text-fg-muted">
            {agentRejected ? `${rejection} Выберите конвейер или другой ключ/модель.` : rejection}
          </p>
          <Button size="sm" variant="secondary" leadingIcon="refresh" onClick={onRetry}>
            Повторить
          </Button>
        </div>
      </Card>
    )
  }
  const estimate = state.data
  if (!estimate) return null
  const refreshing = state.isPending
  const cost = estimateCost(estimate)
  const incomplete = estimateIncomplete(estimate)
  const budgetUsd = budget?.cost_usd ?? null
  return (
    <Card
      variant="outline"
      padding="sm"
      aria-busy={refreshing}
      className={cn(
        'flex flex-col gap-3 transition-opacity duration-base',
        refreshing && 'opacity-60',
      )}
    >
      <div className="flex flex-wrap items-center gap-2">
        <span className="type-subheading text-fg">
          {mode === 'build' ? 'Оценка сборки' : 'Оценка анализа'}
        </span>
        {refreshing && (
          <span className="type-caption text-fg-subtle" role="status">
            Пересчитываю оценку…
          </span>
        )}
        {incomplete && (
          <Badge tone="amber" variant="outline" icon="alert-triangle">
            Неполная
          </Badge>
        )}
        {estimate.model && (
          <span className="ml-auto type-caption text-fg-subtle">{estimate.model}</span>
        )}
      </div>

      {cost ? (
        <CostMeter
          label="Стоимость"
          estimate={cost}
          budget={budgetUsd}
          currency={estimateCurrency(estimate)}
          incomplete={incomplete}
        />
      ) : (
        <div className="flex items-center gap-2 type-caption text-amber-fg">
          <Icon name="alert-triangle" size={14} />
          Цены модели неизвестны — точную стоимость сервер не назовёт
        </div>
      )}

      <div className="flex flex-wrap gap-x-4 gap-y-1 type-caption text-fg-muted" data-numeric>
        <span className="flex items-center gap-1.5">
          <Icon name="clock" size={14} className="text-fg-subtle" />
          {estimateDurationText(estimate)}
        </span>
        <span className="flex items-center gap-1.5">
          <Icon name="list-check" size={14} className="text-fg-subtle" />
          {estimateCallsText(estimate)}
        </span>
        <span className="flex items-center gap-1.5">
          <Icon name="notes" size={14} className="text-fg-subtle" />
          {estimateTokensText(estimate)}
        </span>
      </div>

      {estimate.breakdown.length > 0 && (
        <>
          <Divider />
          <ul aria-label="Оценка по этапам" className="flex flex-col gap-1.5">
            {estimate.breakdown.map((stage) => (
              <li key={stage.stage} className="flex items-baseline justify-between gap-3">
                <span className="min-w-0 truncate type-caption text-fg">{stage.label}</span>
                <span className="shrink-0 type-caption text-fg-subtle" data-numeric>
                  {formatNumberRange(stage.calls.min, stage.calls.max)} запросов
                  {stage.cost && stage.cost.min_usd != null && stage.cost.max_usd != null
                    ? ` \u00B7 ${formatMoneyRange(stage.cost.min_usd, stage.cost.max_usd, stage.cost.currency)}`
                    : ''}
                </span>
              </li>
            ))}
          </ul>
        </>
      )}

      {estimate.notes && estimate.notes.length > 0 && (
        <div className="flex flex-col gap-1 rounded-md bg-bg-subtle px-2.5 py-2">
          {estimate.notes.map((note) => (
            <p key={note} className="type-caption text-fg-muted">
              {note}
            </p>
          ))}
        </div>
      )}

      {estimate.priced_on && (
        <span className="type-caption text-fg-subtle">
          Цены сверены {formatDate(new Date(estimate.priced_on))}
        </span>
      )}
    </Card>
  )
}
