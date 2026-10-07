import { useQuery } from '@tanstack/react-query'
import { useNavigate } from '@tanstack/react-router'
import { type FormEvent, useEffect, useState } from 'react'
import { examplesQueryOptions } from '@/entities/example'
import { useCreateProjectFromExample } from '@/entities/project'
import { ACCEPTED_FILES } from '@/entities/source'
import { appendDictation, VoiceDictation } from '@/features/voice-record/voice-dictation'
import { errorMessage } from '@/shared/api/client'
import { emitOnboardingSignal } from '@/shared/lib/onboarding-signals'
import { TOUR_ANCHORS, tourAnchor } from '@/shared/lib/tour-anchors'
import {
  Button,
  Dialog,
  DialogClose,
  DialogContent,
  EmptyState,
  Field,
  FileDrop,
  Input,
  RadioGroup,
  RadioGroupItem,
  SegmentedControl,
  Skeleton,
  Tag,
  Textarea,
  toast,
} from '@/shared/ui'
import { type CreateMode, useCreateProjectDialog } from './model'
import { useCreateProjectFlow } from './use-create-flow'

const MODES = [
  { value: 'blank' as const, label: 'Пустой', icon: 'folder-plus' as const },
  { value: 'example' as const, label: 'Из примера', icon: 'template' as const },
]

/** Создание проекта: пустого или из демо-примера. После создания — сразу рабочее место. */
export function CreateProjectDialog() {
  const { open, mode, lockMode, setOpen, setMode } = useCreateProjectDialog()
  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogContent
        title="Новый проект"
        size="md"
        aria-describedby={undefined}
        onOpenAutoFocus={(event) => {
          if (mode === 'example') event.preventDefault()
        }}
      >
        <div className="flex flex-col gap-5">
          {!lockMode && (
            <SegmentedControl<CreateMode>
              aria-label="Как создать проект"
              value={mode}
              onValueChange={setMode}
              options={MODES}
            />
          )}
          {mode === 'blank' ? <BlankForm /> : <ExampleForm />}
        </div>
      </DialogContent>
    </Dialog>
  )
}

function useOpenProject() {
  const navigate = useNavigate()
  const close = useCreateProjectDialog((state) => state.setOpen)
  return (projectId: string) => {
    close(false)
    void navigate({ to: '/projects/$projectId', params: { projectId } })
  }
}

/** Подпись результата для уведомления: «Описание не добавлено, схема не запущена». */
function failureSummary(failures: string[]): string {
  const text = failures.join(', ')
  return text.charAt(0).toUpperCase() + text.slice(1)
}

function BlankForm() {
  const { title: initialTitle, minimal, onboarding } = useCreateProjectDialog.getState()
  const [title, setTitle] = useState(initialTitle)
  const [description, setDescription] = useState('')
  const [dictating, setDictating] = useState(false)
  const [files, setFiles] = useState<File[]>([])
  const [error, setError] = useState<string>()
  const create = useCreateProjectFlow()
  const openProject = useOpenProject()

  const submit = (event: FormEvent) => {
    event.preventDefault()
    const name = title.trim()
    if (!name) {
      setError('Назовите проект — например, по процессу: «Приёмка оборудования»')
      return
    }
    // `mutateAsync`, а не `mutate` с колбэками: если диалог закрыли посреди создания, колбэки
    // `mutate` не сработают, а переход в проект и уведомление должны состояться.
    create.mutateAsync({ title: name, description, files, onboarding }).then(
      (result) => {
        emitOnboardingSignal({ type: 'project.created', id: result.projectId })
        if (result.failures.length > 0) {
          toast.error('Проект создан, но не всё получилось', {
            description: failureSummary(result.failures),
            duration: 8000,
          })
        } else if (result.waitTimedOut) {
          toast.success('Проект создан', {
            description: 'Документы ещё обрабатываются. Запустите схему, когда они будут готовы.',
            duration: 8000,
          })
        } else {
          toast.success('Проект создан', {
            description: result.building ? 'Схема уже строится' : result.title,
          })
        }
        openProject(result.projectId)
      },
      (err) => setError(errorMessage(err)),
    )
  }

  const addFiles = (picked: File[]) =>
    setFiles((current) => [
      ...current,
      ...picked.filter(
        (file) => !current.some((item) => item.name === file.name && item.size === file.size),
      ),
    ])

  return (
    <form onSubmit={submit} className="flex flex-col gap-4 animate-fade-in" noValidate>
      <Field label="Название" error={error}>
        <Input
          autoFocus
          value={title}
          maxLength={200}
          placeholder="Технологическое присоединение"
          onChange={(event) => {
            setTitle(event.target.value)
            if (error) setError(undefined)
          }}
        />
      </Field>
      {!minimal && (
        <Field label="Описание процесса" optional>
          <VoiceDictation
            onText={(text) => setDescription((current) => appendDictation(current, text))}
            onActiveChange={setDictating}
          >
            <Textarea
              value={description}
              minRows={3}
              maxRows={7}
              placeholder="Кто, что и в каком порядке делает — как рассказали бы коллеге"
              className="pr-10"
              onChange={(event) => setDescription(event.target.value)}
            />
          </VoiceDictation>
        </Field>
      )}
      {!minimal && (
        <Field label="Документы" optional>
          <div className="flex flex-col gap-2">
            <FileDrop
              size="sm"
              multiple
              accept={ACCEPTED_FILES.join(',')}
              onFiles={addFiles}
              title="Перетащите документы"
              hint=".txt, .md, .csv, .docx, .pdf"
            />
            {files.length > 0 && (
              <ul className="flex flex-wrap gap-1.5" aria-label="Выбранные документы">
                {files.map((file) => (
                  <li key={`${file.name}-${file.size}`} className="max-w-full">
                    <Tag
                      icon="file-text"
                      removeLabel={`Убрать ${file.name}`}
                      onRemove={() =>
                        setFiles((current) => current.filter((item) => item !== file))
                      }
                    >
                      {file.name}
                    </Tag>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </Field>
      )}
      <div className="-mx-5 -mb-5 mt-1 flex justify-end gap-2 border-t border-border px-5 py-3.5">
        <DialogClose asChild>
          <Button variant="ghost">Отмена</Button>
        </DialogClose>
        <Button
          type="submit"
          variant="primary"
          loading={create.isPending}
          disabled={dictating}
          {...tourAnchor(TOUR_ANCHORS.createSubmit)}
        >
          Создать проект
        </Button>
      </div>
    </form>
  )
}

function ExampleForm() {
  const examples = useQuery(examplesQueryOptions)
  const [selected, setSelected] = useState<string>()
  const create = useCreateProjectFromExample()
  const openProject = useOpenProject()

  useEffect(() => {
    if (!selected && examples.data?.[0]) setSelected(examples.data[0].id)
  }, [examples.data, selected])

  const submit = (event: FormEvent) => {
    event.preventDefault()
    if (!selected) return
    create.mutate(selected, {
      onSuccess: (project) => {
        emitOnboardingSignal({ type: 'project.created', id: project.id })
        toast.success('Проект создан из примера', { description: project.title })
        openProject(project.id)
      },
      onError: (err) =>
        toast.error('Не удалось создать проект', { description: errorMessage(err) }),
    })
  }

  return (
    <form onSubmit={submit} className="flex flex-col gap-4 animate-fade-in">
      {examples.isPending ? (
        <div className="flex flex-col gap-2" aria-busy="true">
          {[0, 1, 2].map((key) => (
            <Skeleton key={key} className="h-16 rounded-md" />
          ))}
        </div>
      ) : examples.isError ? (
        <EmptyState
          size="sm"
          backdrop="none"
          icon="alert-circle"
          title="Примеры не загрузились"
          action={
            <Button size="sm" onClick={() => void examples.refetch()}>
              Повторить
            </Button>
          }
        />
      ) : (
        <RadioGroup
          aria-label="Пример"
          value={selected}
          onValueChange={setSelected}
          className="gap-2"
        >
          {examples.data.map((example) => (
            <div
              key={example.id}
              data-selected={selected === example.id || undefined}
              className="rounded-md border border-border bg-surface px-3 py-2.5 transition-[border-color,background-color] duration-base ease-soft hover:border-border-strong data-[selected]:border-accent/50 data-[selected]:bg-accent-subtle/60"
            >
              <RadioGroupItem
                value={example.id}
                label={example.title}
                description={example.description}
              />
            </div>
          ))}
        </RadioGroup>
      )}
      <div className="-mx-5 -mb-5 mt-1 flex justify-end gap-2 border-t border-border px-5 py-3.5">
        <DialogClose asChild>
          <Button variant="ghost">Отмена</Button>
        </DialogClose>
        <Button
          type="submit"
          variant="primary"
          leadingIcon="template"
          disabled={!selected}
          loading={create.isPending}
        >
          Начать с примера
        </Button>
      </div>
    </form>
  )
}
