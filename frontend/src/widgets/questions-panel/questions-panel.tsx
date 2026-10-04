import { AnimatePresence, m } from 'motion/react'
import { useEffect, useMemo, useRef, useState } from 'react'
import { isRunning } from '@/entities/project'
import {
  countByGroup,
  type Question,
  type QuestionGroup,
  questionGroup,
  sortQuestions,
} from '@/entities/question'
import { useStartRun } from '@/entities/run'
import { resolvedExit } from '@/shared/lib/motion'
import {
  Button,
  EmptyState,
  IconButton,
  ScrollArea,
  Tabs,
  TabsList,
  TabsTrigger,
} from '@/shared/ui'
import { useWorkspace, useWorkspaceUi } from '@/widgets/workspace/model'
import { QuestionCard } from './question-card'
import { useQuestionTransitions } from './use-question-transitions'

const TABS: { value: QuestionGroup; label: string }[] = [
  { value: 'open', label: 'Открытые' },
  { value: 'assumed', label: 'Допущения' },
  { value: 'resolved', label: 'Решённые' },
]

/** Правая панель: вопросы по вкладкам статусов с живыми переходами. */
export function QuestionsPanel({ onCollapse }: { onCollapse: () => void }) {
  const { project, selectedQuestionId } = useWorkspace()
  const [tab, setTab] = useState<QuestionGroup>('open')
  const tabRequest = useWorkspaceUi((state) => state.questionsTabRequest)
  const transitions = useQuestionTransitions(project.questions)
  const counts = countByGroup(project.questions.filter((q) => q.status !== 'obsolete'))

  // Вкладку можно попросить снаружи (обучение показывает «Открытые»).
  useEffect(() => {
    if (tabRequest) setTab(tabRequest.tab)
  }, [tabRequest])

  // Выбранный извне вопрос (со схемы, из отчёта) открывает свою вкладку. Только при смене
  // выбора: если вопрос решился, пока выбран, вкладка остаётся — пусть уход будет виден.
  const questionsRef = useRef(project.questions)
  questionsRef.current = project.questions
  useEffect(() => {
    const selected = questionsRef.current.find((question) => question.id === selectedQuestionId)
    if (selected) setTab(questionGroup(selected.status))
  }, [selectedQuestionId])

  const lists = useMemo(() => {
    const sorted = sortQuestions(project.questions)
    const byTab: Record<QuestionGroup, Question[]> = { open: [], assumed: [], resolved: [] }
    for (const question of sorted) {
      const group = transitions.settling.has(question.id) ? 'open' : questionGroup(question.status)
      byTab[group].push(question)
    }
    return byTab
  }, [project.questions, transitions.settling])

  return (
    <section aria-label="Вопросы" className="flex h-full flex-col bg-surface">
      <div className="flex h-11 shrink-0 items-center gap-2 border-b border-border pr-1.5 pl-4">
        <h2 className="type-subheading text-fg">Вопросы</h2>
        <IconButton
          icon="sidebar-right-collapse"
          label="Свернуть панель"
          size="sm"
          className="ml-auto"
          onClick={onCollapse}
        />
      </div>
      <Tabs
        value={tab}
        onValueChange={(value) => setTab(value as QuestionGroup)}
        className="flex min-h-0 flex-1 flex-col"
      >
        <TabsList className="shrink-0 px-2">
          {TABS.map((item) => (
            <TabsTrigger key={item.value} value={item.value} count={counts[item.value]}>
              {item.label}
            </TabsTrigger>
          ))}
        </TabsList>
        <ScrollArea className="min-h-0 flex-1">
          <div className="flex flex-col gap-2.5 p-3 pb-6">
            <AnimatePresence initial={false}>
              {lists[tab].map((question) => (
                <m.div
                  key={question.id}
                  variants={resolvedExit}
                  initial="initial"
                  animate="animate"
                  exit="exit"
                >
                  <QuestionCard
                    question={question}
                    settling={transitions.settling.has(question.id)}
                    fresh={transitions.fresh.has(question.id)}
                  />
                </m.div>
              ))}
            </AnimatePresence>
            {lists[tab].length === 0 && <EmptyTab tab={tab} />}
          </div>
        </ScrollArea>
      </Tabs>
    </section>
  )
}

function EmptyTab({ tab }: { tab: QuestionGroup }) {
  const { project, canEdit } = useWorkspace()
  const start = useStartRun(project.id)
  const noSources = project.sources.length === 0
  if (tab === 'open') {
    if (project.questions.length === 0) {
      return (
        <EmptyState
          size="sm"
          backdrop="dots"
          icon="message-question"
          title={noSources ? 'Вопросов пока нет' : 'Анализ ещё не запускался'}
          description={
            !canEdit
              ? 'Здесь появятся уточняющие вопросы после анализа.'
              : noSources
                ? 'Добавьте источник — после анализа здесь появятся уточняющие вопросы.'
                : 'Модель прочитает источники и спросит о том, что в них неясно.'
          }
          action={
            noSources || !canEdit ? undefined : (
              <Button
                size="sm"
                leadingIcon="sparkles"
                loading={start.isPending}
                disabled={isRunning(project.status)}
                onClick={() => start.mutate('analyze')}
              >
                Запустить анализ
              </Button>
            )
          }
        />
      )
    }
    return (
      <EmptyState
        size="sm"
        backdrop="none"
        icon="circle-check"
        title="Открытых вопросов нет"
        description="Можно строить схему: неотвеченное станет явными допущениями."
      />
    )
  }
  if (tab === 'assumed') {
    return (
      <EmptyState
        size="sm"
        backdrop="none"
        icon="assumption"
        title="Допущений нет"
        description="Сюда попадают вопросы, которые вы решили не уточнять."
      />
    )
  }
  return (
    <EmptyState size="sm" backdrop="none" icon="list-check" title="Решённых вопросов пока нет" />
  )
}
