import { useQuery } from '@tanstack/react-query'
import type { ReactNode } from 'react'
import { useReportOnboardingEvent } from '@/entities/onboarding'
import { diagramElements, type VersionDetail, versionLabel } from '@/entities/version'
import { EXPORT_FORMATS, exportDiagram } from '@/features/export-diagram/export'
import { cn } from '@/shared/lib/cn'
import {
  AssumptionFrame,
  Badge,
  Button,
  Icon,
  type IconName,
  Sheet,
  SheetContent,
  Skeleton,
} from '@/shared/ui'
import { useWorkspace, useWorkspaceUi } from '@/widgets/workspace/model'

/** Отчёт проверки версии: XSD, замечания линтера, допущения, изменения и скачивание. */
export function ReportSheet() {
  const { project, viewedVersionId, versions } = useWorkspace()
  const sheet = useWorkspaceUi((state) => state.sheet)
  const setSheet = useWorkspaceUi((state) => state.setSheet)
  const versionId = viewedVersionId ?? project.latest_version?.id
  const version = useQuery({
    ...versions.detail(versionId ?? ''),
    enabled: sheet === 'report' && !!versionId,
  })
  return (
    <Sheet open={sheet === 'report'} onOpenChange={(open) => setSheet(open ? 'report' : null)}>
      <SheetContent
        size="md"
        title="Проверка схемы"
        description={version.data ? versionLabel(version.data) : undefined}
      >
        {version.data ? (
          <Report version={version.data} />
        ) : (
          <div className="flex flex-col gap-3" aria-busy="true">
            <Skeleton className="h-16 rounded-lg" />
            <Skeleton className="h-24 rounded-lg" />
            <Skeleton className="h-24 rounded-lg" />
          </div>
        )}
      </SheetContent>
    </Sheet>
  )
}

function Report({ version }: { version: VersionDetail }) {
  const { project, editorRef, selectQuestion, focusElements, versions } = useWorkspace()
  const setSheet = useWorkspaceUi((state) => state.setSheet)
  const reportEvent = useReportOnboardingEvent()
  const elements = diagramElements(version.xml)
  const nameOf = (id?: string | null) => (id ? elements.get(id)?.name || id : undefined)
  const { report, diff } = version
  const errors = report.lint.filter((issue) => issue.severity === 'error').length
  const warnings = report.lint.length - errors

  const goTo = (action: () => void) => {
    setSheet(null)
    setTimeout(action, 180)
  }

  // Допущения группируем по вопросу: один вопрос может касаться нескольких элементов.
  const byQuestion = new Map<string, { text: string; elements: string[] }>()
  for (const item of report.assumptions) {
    const entry = byQuestion.get(item.question_id) ?? { text: item.text, elements: [] }
    entry.elements.push(item.element_id)
    byQuestion.set(item.question_id, entry)
  }

  return (
    <div className="flex flex-col gap-6">
      <div className="grid grid-cols-2 gap-2">
        <Check
          ok={report.xsd_valid}
          title={report.xsd_valid ? 'XSD: схема валидна' : 'XSD: есть ошибки'}
          text="BPMN 2.0, открывается в Camunda и bpmn.io"
        />
        <Check
          ok={errors === 0}
          warn={errors === 0 && warnings > 0}
          title={
            report.lint.length === 0
              ? 'bpmnlint: без замечаний'
              : `bpmnlint: ${errors > 0 ? `ошибок ${errors}` : `предупреждений ${warnings}`}`
          }
          text="Правила моделирования recommended"
        />
      </div>

      {report.lint.length > 0 && (
        <Section title="Замечания линтера" icon="alert-triangle">
          <ul className="flex flex-col divide-y divide-border rounded-lg border border-border">
            {report.lint.map((issue, index) => (
              // biome-ignore lint/suspicious/noArrayIndexKey: замечания без id
              <li key={index} className="flex items-start gap-2.5 px-3 py-2.5">
                <Icon
                  name={issue.severity === 'error' ? 'alert-circle' : 'alert-triangle'}
                  size={16}
                  className={cn(
                    'mt-0.5 shrink-0',
                    issue.severity === 'error' ? 'text-danger' : 'text-amber',
                  )}
                />
                <div className="flex min-w-0 flex-1 flex-col gap-0.5">
                  <span className="type-ui text-fg">{issue.message}</span>
                  <span className="type-code text-fg-subtle">{issue.rule}</span>
                </div>
                {issue.element_id && (
                  <Button
                    size="sm"
                    variant="ghost"
                    leadingIcon="locate"
                    onClick={() => goTo(() => focusElements([issue.element_id as string]))}
                  >
                    {nameOf(issue.element_id)}
                  </Button>
                )}
              </li>
            ))}
          </ul>
        </Section>
      )}

      <Section title="Допущения" icon="assumption" count={byQuestion.size}>
        {byQuestion.size === 0 ? (
          <p className="type-ui text-fg-muted">
            Схема построена без допущений: на все вопросы есть ответы.
          </p>
        ) : (
          <div className="flex flex-col gap-2">
            {[...byQuestion.entries()].map(([questionId, entry]) => {
              const question = project.questions.find((item) => item.id === questionId)
              return (
                <AssumptionFrame
                  key={questionId}
                  label={question ? `${question.code}: ${question.text}` : 'Допущение'}
                  actions={
                    question && (
                      <Button
                        size="sm"
                        variant="ghost"
                        trailingIcon="arrow-right"
                        onClick={() => goTo(() => selectQuestion(question.id, { focus: true }))}
                      >
                        К вопросу
                      </Button>
                    )
                  }
                >
                  <span className="flex flex-col gap-1.5">
                    {entry.text}
                    <span className="flex flex-wrap gap-1">
                      {entry.elements.map((elementId) => (
                        <Badge key={elementId} tone="amber" variant="outline" icon="diagram">
                          {nameOf(elementId)}
                        </Badge>
                      ))}
                    </span>
                  </span>
                </AssumptionFrame>
              )
            })}
          </div>
        )}
      </Section>

      {version.number > 1 && (
        <Section title={`Изменения к версии ${version.number - 1}`} icon="compare">
          <div className="grid grid-cols-3 gap-2">
            <DiffStat label="Добавлено" value={diff.added} tone="success" icon="plus" />
            <DiffStat label="Удалено" value={diff.removed} tone="danger" icon="minus" />
            <DiffStat label="Изменено" value={diff.changed} tone="amber" icon="pencil" />
          </div>
        </Section>
      )}

      <Section title="Скачать" icon="download">
        <div className="flex flex-wrap gap-2">
          {EXPORT_FORMATS.map((item) => (
            <Button
              key={item.format}
              leadingIcon={item.icon}
              onClick={() =>
                void exportDiagram({
                  format: item.format,
                  versionId: version.id,
                  versionNumber: version.number,
                  title: project.title,
                  editor: editorRef.current,
                  xmlUrl: versions.xmlUrl(version.id),
                  onSaved: () => reportEvent.mutate('diagram_exported'),
                })
              }
            >
              {item.format === 'bpmn' ? '.bpmn' : item.format === 'svg' ? '.svg' : '.png'}
            </Button>
          ))}
        </div>
      </Section>
    </div>
  )
}

function Check({
  ok,
  warn = false,
  title,
  text,
}: {
  ok: boolean
  warn?: boolean
  title: string
  text: string
}) {
  const tone = !ok ? 'danger' : warn ? 'amber' : 'success'
  return (
    <div
      className={cn(
        'flex flex-col gap-2 rounded-lg border p-3',
        tone === 'success' && 'border-success/30 bg-success-subtle/60',
        tone === 'amber' && 'border-amber/40 bg-amber-subtle/60',
        tone === 'danger' && 'border-danger/40 bg-danger-subtle/60',
      )}
    >
      <Icon
        name={
          tone === 'success' ? 'shield-check' : tone === 'amber' ? 'alert-triangle' : 'alert-circle'
        }
        size={20}
        className={cn(
          tone === 'success' && 'text-success',
          tone === 'amber' && 'text-amber',
          tone === 'danger' && 'text-danger',
        )}
      />
      <span className="type-subheading text-fg">{title}</span>
      <span className="type-caption text-fg-muted">{text}</span>
    </div>
  )
}

function DiffStat({
  label,
  value,
  tone,
  icon,
}: {
  label: string
  value: number
  tone: 'success' | 'danger' | 'amber'
  icon: IconName
}) {
  return (
    <div className="flex flex-col gap-1 rounded-lg border border-border bg-bg-subtle px-3 py-2.5">
      <span className="flex items-center gap-1.5 type-caption text-fg-muted">
        <Icon
          name={icon}
          size={14}
          className={cn(
            value === 0 && 'text-fg-subtle',
            value > 0 && tone === 'success' && 'text-success',
            value > 0 && tone === 'danger' && 'text-danger',
            value > 0 && tone === 'amber' && 'text-amber',
          )}
        />
        {label}
      </span>
      <span className="type-heading text-fg" data-numeric>
        {value}
      </span>
    </div>
  )
}

function Section({
  title,
  icon,
  count,
  children,
}: {
  title: string
  icon: IconName
  count?: number
  children: ReactNode
}) {
  return (
    <section className="flex flex-col gap-2.5">
      <h3 className="flex items-center gap-1.5 type-label text-fg-muted">
        <Icon name={icon} size={14} />
        {title}
        {count !== undefined && count > 0 && (
          <span className="text-fg-subtle" data-numeric>
            {count}
          </span>
        )}
      </h3>
      {children}
    </section>
  )
}
