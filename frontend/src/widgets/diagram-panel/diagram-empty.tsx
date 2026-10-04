import { isRunning } from '@/entities/project'
import { useStartRun } from '@/entities/run'
import { ACCEPTED_FILES } from '@/entities/source'
import { useFileUploads } from '@/features/add-source/use-file-uploads'
import { Button, EmptyState, GridBackdrop, Icon, type IconName } from '@/shared/ui'
import { useWorkspace, useWorkspaceUi } from '@/widgets/workspace/model'

/**
 * Схемы ещё нет. Без источников — онбординг «с чего начать»; с источниками — одно понятное
 * действие: построить схему (неотвеченные вопросы станут допущениями).
 */
export function DiagramEmpty() {
  const { project, canEdit } = useWorkspace()
  const start = useStartRun(project.id)
  const running = isRunning(project.status)
  const building = project.status === 'building'

  if (project.sources.length === 0 && canEdit) return <Onboarding />

  return (
    <EmptyState
      className="h-full"
      icon="diagram"
      title={building ? 'Схема собирается' : 'Схемы пока нет'}
      description={
        building
          ? 'Схема появится здесь, как только прогон дойдёт до раскладки.'
          : !canEdit
            ? 'В этом проекте её ещё не строили.'
            : 'Постройте её сейчас: на неотвеченные вопросы модель примет допущения и подсветит их на схеме.'
      }
      action={
        building || !canEdit ? undefined : (
          <>
            <Button
              variant="primary"
              leadingIcon="diagram"
              disabled={running}
              loading={start.isPending && start.variables === 'build'}
              onClick={() => start.mutate('build')}
            >
              Построить схему
            </Button>
            {project.questions.length === 0 && (
              <Button
                leadingIcon="sparkles"
                disabled={running}
                loading={start.isPending && start.variables === 'analyze'}
                onClick={() => start.mutate('analyze')}
              >
                Сначала анализ
              </Button>
            )}
          </>
        )
      }
    />
  )
}

function Onboarding() {
  const { project } = useWorkspace()
  const setDialog = useWorkspaceUi((state) => state.setDialog)
  const { upload } = useFileUploads(project.id)

  const pickFile = () => {
    const input = document.createElement('input')
    input.type = 'file'
    input.accept = ACCEPTED_FILES.join(',')
    input.multiple = true
    input.onchange = () => upload(Array.from(input.files ?? []))
    input.click()
  }

  return (
    <div className="@container relative isolate flex h-full flex-col items-center justify-center gap-8 px-8">
      <GridBackdrop pattern="grid" glow />
      <div className="flex max-w-lg flex-col items-center gap-2 text-center">
        <h2 className="type-title text-fg">С чего начнём</h2>
        <p className="type-body text-fg-muted">
          Добавьте всё, что известно о процессе. Модель задаст вопросы о неясном и соберёт схему.
        </p>
      </div>
      <div className="grid w-full max-w-3xl grid-cols-1 gap-3 @2xl:grid-cols-3">
        <StartTile
          icon="notes"
          title="Вставить текст"
          text="Регламент, письмо, заметка"
          onClick={() => setDialog('text')}
        />
        <StartTile
          icon="file-upload"
          title="Загрузить документ"
          text=".docx, .pdf, .md, .txt"
          onClick={pickFile}
        />
        <StartTile
          icon="microphone"
          title="Надиктовать"
          text="Расскажите, как всё устроено"
          onClick={() => setDialog('voice')}
        />
      </div>
    </div>
  )
}

function StartTile({
  icon,
  title,
  text,
  onClick,
}: {
  icon: IconName
  title: string
  text: string
  onClick: () => void
}) {
  return (
    <Button
      variant="secondary"
      onClick={onClick}
      className="group/tile h-auto justify-start whitespace-normal rounded-lg p-4 text-left shadow-sm hover:shadow-md [&>span]:flex-col [&>span]:items-start [&>span]:gap-3"
    >
      <span className="grid size-9 place-items-center rounded-md border border-border bg-bg-subtle text-fg-muted transition-colors duration-base group-hover/tile:border-accent/40 group-hover/tile:text-accent-fg">
        <Icon name={icon} size={20} />
      </span>
      <span className="flex flex-col gap-0.5">
        <span className="type-subheading text-fg">{title}</span>
        <span className="type-caption font-normal text-fg-muted">{text}</span>
      </span>
    </Button>
  )
}
