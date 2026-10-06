import { useInfiniteQuery, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useMemo, useRef } from 'react'
import {
  type OnboardingState,
  useOnboardingUi,
  useRestartTour,
  useUpdateTour,
} from '@/entities/onboarding'
import { projectQueryOptions, projectsInfiniteOptions } from '@/entities/project'
import { sortQuestions } from '@/entities/question'
import { useRunView, useStartRun } from '@/entities/run'
import { useCurrentUser } from '@/entities/session'
import { useCreateProjectDialog } from '@/features/create-project/model'
import { TourHost, useTourStore } from '@/features/onboarding/tour'
import type { TourContext, TourUi } from '@/features/onboarding/tour/context'
import { CHAPTERS, COPY, FIRST_PROJECT_TITLE } from '@/features/onboarding/tour/copy'
import { createTourPersistence } from '@/features/onboarding/tour/create-persistence'
import { resetTourSession, useTourSession } from '@/features/onboarding/tour/session'
import { tourSteps } from '@/features/onboarding/tour/steps'
import { useAnchorPresence } from '@/features/onboarding/tour/use-anchor-presence'
import { useShareDialogControl } from '@/features/share-project/model'
import { ApiError } from '@/shared/api/client'
import { toast } from '@/shared/ui'
import { useWorkspaceUi } from '@/widgets/workspace/model'

/** Шаги, на которых нужно знать, открыты ли окна (кнопка меню или поле окна). */
const PRESENCE_STEPS = new Set([
  'project.create',
  'sources.text',
  'sources.voice',
  'question.answer',
  'share.create',
])
/** С этих шагов итог прогона уже известен — после перезагрузки его берём из данных проекта. */
const AFTER_RUN = new Set([
  'run.wait',
  'question.answer',
  'question.ignore',
  'diagram.tour',
  'share.create',
  'finish',
])

/** Рычаги экрана: публичные точки расширения фич и виджетов, тур о них больше ничего не знает. */
const ui: TourUi = {
  expandPanel: (panel) => useWorkspaceUi.getState().expandPanel(panel),
  showOpenQuestions: () => useWorkspaceUi.getState().showQuestionsTab('open'),
  setTextSuggestion: (text) => useWorkspaceUi.getState().setTextSuggestion(text),
  interceptCreate: (title) =>
    useCreateProjectDialog.getState().setInterceptor(
      title
        ? (options) => ({
            ...options,
            mode: 'blank',
            title: title(),
            lockMode: true,
            minimal: true,
            onboarding: true,
          })
        : null,
    ),
  closeDialogs: () => useWorkspaceUi.getState().setDialog(null),
  closeShareDialog: () => useShareDialogControl.getState().requestClose(),
  openChecklist: () => useOnboardingUi.getState().openChecklist(),
}

/**
 * Сборка тура: контекст шагов из данных учебного проекта, хранение прогресса на сервере, хост.
 * Грузится лениво, когда тур идёт (или сервер говорит, что идёт). Всё про экран берётся из
 * публичных точек расширения; фичи про тур ничего не знают.
 */
export default function TourRoot({ state }: { state: OnboardingState }) {
  const client = useQueryClient()
  const userId = useCurrentUser()?.id
  const update = useUpdateTour()
  const restart = useRestartTour()
  const tourActive = useTourStore((s) => s.status === 'active')
  const stepKey = useTourStore((s) => s.stepKey)
  const session = useTourSession()

  const serverProjectId = state.tour?.project_id ?? null
  const projectId = session.projectId ?? serverProjectId
  const serverProjectRef = useRef(serverProjectId)
  serverProjectRef.current = serverProjectId
  // Сессия знает учебный проект с сервера: сигналы прогонов других проектов она не пропускает.
  const { setServerProjectId } = session
  useEffect(() => setServerProjectId(serverProjectId), [serverProjectId, setServerProjectId])

  const project = useQuery({
    ...projectQueryOptions(projectId ?? ''),
    enabled: tourActive && Boolean(projectId),
    retry: false,
  })
  const runView = useRunView(projectId ?? '')
  const startRun = useStartRun(projectId ?? '')
  const presence = useAnchorPresence(tourActive && PRESENCE_STEPS.has(stepKey ?? ''))

  // Название нового учебного проекта: повторный тур не дублирует прежнее.
  const existing = useInfiniteQuery({
    ...projectsInfiniteOptions(FIRST_PROJECT_TITLE, 'own'),
    enabled: tourActive && stepKey === 'project.create',
    select: (data) => data.pages[0]?.total ?? 0,
  })
  const titleRef = useRef(FIRST_PROJECT_TITLE)
  titleRef.current = existing.data
    ? `${FIRST_PROJECT_TITLE} (${existing.data + 1})`
    : FIRST_PROJECT_TITLE

  const data = project.data
  const deleted = project.error instanceof ApiError && project.error.status === 404
  const questions = data ? sortQuestions(data.questions) : []
  const openQuestionIds = questions.filter((q) => q.status === 'open').map((q) => q.id)

  // Итог прогона по данным проекта: после перезагрузки, а также когда прогон закончился, пока никто
  // не слушал (тур на паузе, поток потерян, трекер размонтирован). Пока «Повторить» не стартовал,
  // данные прежнего прогона итогом нового не считаются. Уже отвеченные и проигнорированные вопросы
  // считаются тоже: шаг 8 после перезагрузки не должен исчезнуть из-за ответа в шаге 7.
  const { retryPending, runResult, setRunResult, setPickedId, pickedId } = session
  const askedCount = questions.filter(
    (q) => q.status === 'open' || q.status === 'answered' || q.status === 'ignored',
  ).length
  useEffect(() => {
    if (!tourActive || !stepKey || !AFTER_RUN.has(stepKey)) return
    if (!data || data.active_run || retryPending || runResult) return
    setRunResult({
      status: data.latest_version ? 'succeeded' : 'failed',
      openQuestions: askedCount,
      hasDiagram: Boolean(data.latest_version),
    })
  }, [tourActive, stepKey, data, retryPending, runResult, setRunResult, askedCount])

  // Вопрос шага 7 закрепляется при входе: оптимистичный ответ не уводит прожектор на соседа.
  const firstOpen = openQuestionIds[0]
  useEffect(() => {
    if (tourActive && stepKey === 'question.answer' && !pickedId && firstOpen)
      setPickedId(firstOpen)
  }, [tourActive, stepKey, pickedId, firstOpen, setPickedId])

  const persistence = useMemo(
    () => createTourPersistence({ client, userId, update: update.mutateAsync }),
    [client, userId, update.mutateAsync],
  )

  const context: TourContext = {
    get projectId() {
      return useTourSession.getState().projectId ?? serverProjectRef.current
    },
    loaded: Boolean(data),
    deleted,
    get firstTitle() {
      return titleRef.current
    },
    sources: data?.sources.length ?? 0,
    processing: data?.sources.filter((source) => source.status === 'processing').length ?? 0,
    runActive: Boolean(data?.active_run),
    get queued() {
      return (
        useTourSession.getState().runStatus === 'queued' || data?.active_run?.status === 'queued'
      )
    },
    stage: runView?.stage ?? null,
    get result() {
      return useTourSession.getState().runResult
    },
    openQuestionIds,
    get pickedId() {
      const current = useTourSession.getState()
      return current.pickedId ?? current.answeredId
    },
    get shareCreated() {
      return useTourSession.getState().shareCreated
    },
    present: presence,
    textSuggestion: state.tour_text_suggestion ?? null,
    ui,
    ops: {
      restart: async () => {
        resetTourSession()
        await restart.mutateAsync()
      },
      retryRun: () => {
        const session = useTourSession.getState()
        const previous = session.runResult
        session.setRunResult(null)
        session.setRetryPending(true)
        // Не запустился (409, 429): возвращаем прежний итог, иначе шаг ждал бы вечно.
        startRun.mutate('build', {
          onError: () => {
            useTourSession.getState().setRunResult(previous)
            useTourSession.getState().setRetryPending(false)
          },
        })
      },
    },
  }

  return (
    <TourHost
      enabled={state.tour?.status === 'active'}
      steps={tourSteps}
      context={context}
      persistence={persistence}
      chapters={CHAPTERS}
      onEnd={(reason) => {
        resetTourSession()
        if (reason === 'completed') toast.success(COPY.finish.toast)
      }}
    />
  )
}
