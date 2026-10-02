import { useQuery } from '@tanstack/react-query'
import { useNavigate } from '@tanstack/react-router'
import { type FormEvent, useEffect, useState } from 'react'
import { examplesQueryOptions } from '@/entities/example'
import { useCreateProject, useCreateProjectFromExample } from '@/entities/project'
import { errorMessage } from '@/shared/api/client'
import {
  Button,
  Dialog,
  DialogClose,
  DialogContent,
  EmptyState,
  Field,
  Input,
  RadioGroup,
  RadioGroupItem,
  SegmentedControl,
  Skeleton,
  Textarea,
  toast,
} from '@/shared/ui'
import { type CreateMode, useCreateProjectDialog } from './model'

const MODES = [
  { value: 'blank' as const, label: 'Пустой', icon: 'folder-plus' as const },
  { value: 'example' as const, label: 'Из примера', icon: 'template' as const },
]

/** Создание проекта: пустого или из демо-примера. После создания — сразу рабочее место. */
export function CreateProjectDialog() {
  const { open, mode, setOpen, setMode } = useCreateProjectDialog()
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
          <SegmentedControl<CreateMode>
            aria-label="Как создать проект"
            value={mode}
            onValueChange={setMode}
            options={MODES}
          />
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

function BlankForm() {
  const [title, setTitle] = useState('')
  const [description, setDescription] = useState('')
  const [error, setError] = useState<string>()
  const create = useCreateProject()
  const openProject = useOpenProject()

  const submit = (event: FormEvent) => {
    event.preventDefault()
    const name = title.trim()
    if (!name) {
      setError('Назовите проект — например, по процессу: «Приёмка оборудования»')
      return
    }
    create.mutate(
      { title: name, description: description.trim() || null },
      {
        onSuccess: (project) => {
          toast.success('Проект создан', { description: project.title })
          openProject(project.id)
        },
        onError: (err) => setError(errorMessage(err)),
      },
    )
  }

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
      <Field label="Описание" optional>
        <Textarea
          value={description}
          minRows={2}
          maxRows={6}
          placeholder="Какой процесс описываем и для кого"
          onChange={(event) => setDescription(event.target.value)}
        />
      </Field>
      <div className="-mx-5 -mb-5 mt-1 flex justify-end gap-2 border-t border-border px-5 py-3.5">
        <DialogClose asChild>
          <Button variant="ghost">Отмена</Button>
        </DialogClose>
        <Button type="submit" variant="primary" loading={create.isPending}>
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
