import { AnimatePresence, m } from 'motion/react'
import { useState } from 'react'
import {
  ACCEPTED_FILES,
  ACCEPTED_FILES_HINT,
  buildSourceTree,
  derivationLabel,
  isDerived,
  isMediaFile,
  type Source,
  type SourceNode,
  sourceKindOf,
  sourceMeta,
  useAddSampleSource,
  useDeleteSource,
  useSamples,
  useUpdateSource,
} from '@/entities/source'
import { useFileUploads } from '@/features/add-source/use-file-uploads'
import { cn } from '@/shared/lib/cn'
import { listItem } from '@/shared/lib/motion'
import { TOUR_ANCHORS, tourAnchor } from '@/shared/lib/tour-anchors'
import {
  Badge,
  Button,
  ConfirmDialog,
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
  dragHasFiles,
  FileDrop,
  Icon,
  IconButton,
  Progress,
  ScrollArea,
  Switch,
  Tooltip,
} from '@/shared/ui'
import { useWorkspace, useWorkspaceUi } from '@/widgets/workspace/model'

/** Левая панель: источники проекта, добавление текста, файла и голоса. */
export function SourcesPanel({ onCollapse }: { onCollapse: () => void }) {
  const { project, canEdit } = useWorkspace()
  const setDialog = useWorkspaceUi((state) => state.setDialog)
  const { uploads, upload } = useFileUploads(project.id)
  const [dragging, setDragging] = useState(false)
  // Дерево материалов (RFC-0006): исходные файлы и вложенные производные узлы.
  const tree = buildSourceTree(project.sources.filter((source) => source.kind !== 'answer'))
  const answers = project.sources.filter((source) => source.kind === 'answer')

  return (
    <section
      aria-label="Источники"
      className="relative flex h-full flex-col bg-bg-subtle"
      onDragEnter={(event) => {
        if (canEdit && dragHasFiles(event)) setDragging(true)
      }}
      onDragLeave={(event) => {
        // Файл увели за пределы панели — прячем зону.
        if (!event.currentTarget.contains(event.relatedTarget as Node | null)) setDragging(false)
      }}
      onDrop={() => setDragging(false)}
    >
      <div className="flex h-11 shrink-0 items-center gap-2 border-b border-border pr-1.5 pl-4">
        <h2 className="type-subheading text-fg">Источники</h2>
        <span className="type-caption text-fg-subtle" data-numeric>
          {tree.length}
        </span>
        <div className="ml-auto flex items-center gap-0.5">
          {canEdit && <AddSourceMenu projectId={project.id} onPick={setDialog} onFiles={upload} />}
          <IconButton
            icon="sidebar-left-collapse"
            label="Свернуть панель"
            size="sm"
            onClick={onCollapse}
          />
        </div>
      </div>

      <ScrollArea className="min-h-0 flex-1">
        <div className="flex flex-col gap-4 p-2 pb-4">
          <ul className="flex flex-col gap-0.5">
            <AnimatePresence initial={false}>
              {tree.map((node) => (
                <m.li
                  key={node.source.id}
                  variants={listItem}
                  initial="initial"
                  animate="animate"
                  exit="exit"
                >
                  <SourceBranch node={node} />
                </m.li>
              ))}
              {uploads.map((item) => (
                <m.li
                  key={item.id}
                  variants={listItem}
                  initial="initial"
                  animate="animate"
                  exit="exit"
                  className="flex flex-col gap-2 rounded-md px-2 py-2"
                >
                  <div className="flex items-center gap-2.5">
                    <span className="grid size-7 shrink-0 place-items-center rounded-md border border-border bg-surface text-fg-subtle">
                      <Icon name="upload" size={14} />
                    </span>
                    <span className="min-w-0 flex-1 truncate type-ui text-fg">{item.name}</span>
                    <span className="type-caption text-fg-subtle" data-numeric>
                      {Math.round(item.progress * 100)}%
                    </span>
                  </div>
                  <Progress value={item.progress * 100} label={`Загрузка ${item.name}`} />
                </m.li>
              ))}
            </AnimatePresence>
          </ul>

          {answers.length > 0 && <AnswersGroup answers={answers} />}

          {canEdit && (
            <FileDrop
              size="sm"
              accept={ACCEPTED_FILES.join(',')}
              multiple
              onFiles={upload}
              title="Перетащите документ"
              hint={ACCEPTED_FILES_HINT}
              className="mx-1"
            />
          )}
        </div>
      </ScrollArea>

      {canEdit && dragging && (
        <FileDrop
          accept={ACCEPTED_FILES.join(',')}
          multiple
          onFiles={(files) => {
            setDragging(false)
            upload(files)
          }}
          title="Отпустите, чтобы загрузить"
          hint={ACCEPTED_FILES_HINT}
          className="absolute inset-2 z-10 animate-fade-in border-accent bg-accent-subtle/90 backdrop-blur-sm"
        />
      )}
    </section>
  )
}

function AddSourceMenu({
  projectId,
  onPick,
  onFiles,
}: {
  projectId: string
  onPick: (dialog: 'text' | 'voice') => void
  onFiles: (files: File[]) => void
}) {
  // Список материалов один на всех и не меняется: грузим заранее, чтобы меню открывалось целиком.
  const samples = useSamples()
  const addSample = useAddSampleSource(projectId)
  const pickFile = () => {
    const input = document.createElement('input')
    input.type = 'file'
    input.accept = ACCEPTED_FILES.join(',')
    input.multiple = true
    input.onchange = () => onFiles(Array.from(input.files ?? []))
    input.click()
  }
  return (
    <DropdownMenu>
      <Tooltip content="Добавить источник">
        <DropdownMenuTrigger asChild>
          <IconButton
            icon="plus"
            label="Добавить источник"
            size="sm"
            tooltip={false}
            {...tourAnchor(TOUR_ANCHORS.sourcesAdd)}
          />
        </DropdownMenuTrigger>
      </Tooltip>
      <DropdownMenuContent align="end" className="min-w-52">
        <DropdownMenuItem icon="notes" onSelect={() => onPick('text')}>
          Текст
        </DropdownMenuItem>
        <DropdownMenuItem icon="file-upload" onSelect={pickFile}>
          Документ
        </DropdownMenuItem>
        <DropdownMenuItem icon="microphone" onSelect={() => onPick('voice')}>
          Голосовая заметка
        </DropdownMenuItem>
        {samples.data && samples.data.length > 0 && (
          <>
            <DropdownMenuSeparator />
            <DropdownMenuLabel>Примеры</DropdownMenuLabel>
            {samples.data.map((sample) => (
              <DropdownMenuItem
                key={sample.id}
                icon={sample.kind === 'voice' ? 'microphone' : 'file-description'}
                disabled={addSample.isPending}
                onSelect={() => addSample.mutate(sample.id)}
              >
                <span className="truncate">{sample.title}</span>
              </DropdownMenuItem>
            ))}
          </>
        )}
      </DropdownMenuContent>
    </DropdownMenu>
  )
}

/** Исходный материал и вложенные производные узлы (расшифровка и т. п.) с отступом и линией. */
function SourceBranch({ node }: { node: SourceNode }) {
  return (
    <>
      <SourceRow source={node.source} derivedCount={node.children.length} />
      {node.children.length > 0 && (
        <ul
          aria-label={`Получено из «${node.source.title}»`}
          className="ml-5 flex flex-col gap-0.5 border-l border-border pl-1.5"
        >
          {node.children.map((child) => (
            <li key={child.source.id}>
              <SourceBranch node={child} />
            </li>
          ))}
        </ul>
      )}
    </>
  )
}

function processingLabel(source: Source): string {
  if (source.derivation?.capability === 'speech_to_text') return 'Расшифровываю запись'
  if (isMediaFile(source.file_name)) return 'Обрабатываю запись'
  return 'Разбираю документ'
}

function SourceRow({ source, derivedCount }: { source: Source; derivedCount: number }) {
  const { project, canEdit, openSource } = useWorkspace()
  const update = useUpdateSource(project.id)
  const remove = useDeleteSource(project.id)
  const [confirm, setConfirm] = useState(false)
  const kind = sourceKindOf(source)
  const derived = isDerived(source)
  const producer = derivationLabel(source)
  const processing = source.status === 'processing'
  const failed = source.status === 'failed'
  const warned = source.status === 'ready' && Boolean(source.warning)

  return (
    <div
      className={cn(
        'group/source relative flex items-center gap-2.5 rounded-md px-2 py-1.5 transition-colors duration-base ease-soft hover:bg-hover',
        !source.active && 'opacity-60',
      )}
    >
      <span
        className={cn(
          'grid size-7 shrink-0 place-items-center rounded-md border border-border bg-surface text-fg-muted shadow-xs',
          failed && 'border-danger/40 text-danger-fg',
        )}
      >
        <Icon name={failed ? 'alert-circle' : kind.icon} size={14} />
      </span>
      {/* Вся строка открывает источник; переключатель и меню — поверх. */}
      <a
        href={`?source=${source.id}`}
        onClick={(event) => {
          event.preventDefault()
          openSource(source.id)
        }}
        className="flex min-w-0 flex-1 flex-col outline-none after:absolute after:inset-0 after:rounded-md focus-visible:after:ring-2 focus-visible:after:ring-focus-ring"
      >
        <span className="truncate type-ui text-fg">{source.title}</span>
        <span
          className="flex min-w-0 items-center gap-1.5 truncate type-caption text-fg-subtle"
          data-numeric
        >
          {derived && (
            <Badge tone="accent" icon="sparkles" className="shrink-0">
              ИИ
            </Badge>
          )}
          {processing ? (
            processingLabel(source)
          ) : failed ? (
            <span className="truncate text-danger-fg">
              {source.error ?? 'Не удалось разобрать'}
            </span>
          ) : warned ? (
            <span className="flex min-w-0 items-center gap-1 text-amber-fg">
              <Icon name="alert-triangle" size={14} />
              <span className="truncate">{source.warning}</span>
            </span>
          ) : (
            <>
              <span>{producer ?? kind.label}</span>
              <span aria-hidden="true" className="h-3 w-px bg-border-strong" />
              <span>{sourceMeta(source)}</span>
              {source.edited_by_human && (
                <>
                  <span aria-hidden="true" className="h-3 w-px bg-border-strong" />
                  <span>изменено человеком</span>
                </>
              )}
            </>
          )}
        </span>
        {processing && <Progress label={processingLabel(source)} className="mt-1.5" />}
      </a>
      <div className="relative z-10 flex items-center gap-0.5">
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <IconButton
              icon="dots"
              label={`Действия с источником ${source.title}`}
              size="sm"
              tooltip={false}
              className="opacity-0 transition-opacity duration-base group-hover/source:opacity-100 focus-visible:opacity-100 data-[state=open]:opacity-100"
            />
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end">
            <DropdownMenuItem icon="eye" onSelect={() => openSource(source.id)}>
              Открыть
            </DropdownMenuItem>
            {canEdit && (
              <>
                <DropdownMenuSeparator />
                <DropdownMenuItem icon="trash" tone="danger" onSelect={() => setConfirm(true)}>
                  Удалить
                </DropdownMenuItem>
              </>
            )}
          </DropdownMenuContent>
        </DropdownMenu>
        <Tooltip content={source.active ? 'Участвует в анализе' : 'Не участвует в анализе'}>
          <span className="inline-flex">
            <Switch
              checked={source.active}
              disabled={processing || !canEdit}
              aria-label={`Использовать «${source.title}» в анализе`}
              onCheckedChange={(active) => update.mutate({ id: source.id, active })}
            />
          </span>
        </Tooltip>
      </div>
      <ConfirmDialog
        open={confirm}
        onOpenChange={setConfirm}
        title={`Удалить «${source.title}»?`}
        description={
          derivedCount > 0
            ? 'Вместе с ним удалятся полученные из него материалы. Вопросы, решённые по ним, при следующем анализе могут вернуться в открытые.'
            : 'Вопросы, решённые по этому источнику, при следующем анализе могут вернуться в открытые.'
        }
        confirmLabel="Удалить"
        tone="danger"
        onConfirm={() => remove.mutate(source.id)}
      />
    </div>
  )
}

function AnswersGroup({ answers }: { answers: Source[] }) {
  const { project, selectQuestion } = useWorkspace()
  const [open, setOpen] = useState(false)
  const codeOf = (id?: string | null) =>
    project.questions.find((question) => question.id === id)?.code
  return (
    <div className="flex flex-col gap-0.5 border-t border-border pt-3">
      <Button
        variant="ghost"
        size="sm"
        aria-expanded={open}
        onClick={() => setOpen((value) => !value)}
        className="justify-start px-2 text-fg-subtle"
      >
        <Icon
          name="chevron-right"
          size={14}
          className={cn(
            '-ml-0.5 transition-transform duration-base ease-soft',
            open && 'rotate-90',
          )}
        />
        Ответы на вопросы
        <span data-numeric className="ml-auto">
          {answers.length}
        </span>
      </Button>
      {open && (
        <ul className="flex flex-col gap-0.5 animate-fade-in">
          {answers.map((answer) => (
            <li key={answer.id}>
              <a
                href={`?question=${answer.question_id ?? ''}`}
                onClick={(event) => {
                  event.preventDefault()
                  if (answer.question_id) selectQuestion(answer.question_id, { focus: true })
                }}
                className="flex items-start gap-2.5 rounded-md px-2 py-1.5 outline-none transition-colors duration-base hover:bg-hover focus-visible:ring-2 focus-visible:ring-focus-ring"
              >
                <Icon name="message-question" size={14} className="mt-0.5 text-fg-subtle" />
                <span className="flex min-w-0 flex-1 flex-col">
                  <span className="type-label text-fg-muted">{codeOf(answer.question_id)}</span>
                  <span className="line-clamp-2 type-caption text-fg-muted">{answer.content}</span>
                </span>
              </a>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
