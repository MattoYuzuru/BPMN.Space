import { createFileRoute } from '@tanstack/react-router'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { getLocalProject, type LocalProject, saveLocalProject } from '@/features/local-bpmn'
import { Button, Card, Icon, IconButton, ScrollArea, Textarea } from '@/shared/ui'
import type { DiagramEditorHandle } from '@/widgets/diagram-editor'
import { LazyDiagramEditor } from '@/widgets/diagram-editor'
import './home.css'

interface ProjectInfo {
  id: string
  title: string
  description?: string | null
  questions?: Array<{
    id: string
    code: string
    text: string
    assumption: string
    status: string
    element_ids: string[]
  }>
  latest_version?: {
    id: string
    number: number
    report: { xsd_valid: boolean; lint: Array<{ message: string; severity: string }> }
  } | null
  active_run?: { id: string; status: string; stage_label: string; progress: number } | null
}

interface AssistantMessage {
  id: string
  role: 'assistant' | 'user'
  text: string
}

export const Route = createFileRoute('/studio/$projectId')({ component: StudioPage })

async function api<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch(`/api/v1${path}`, options)
  if (!response.ok) throw new Error(`API ${response.status}`)
  return response.json() as Promise<T>
}

function StudioPage() {
  const { projectId } = Route.useParams()
  const [project, setProject] = useState<ProjectInfo | null>(null)
  const [local, setLocal] = useState<LocalProject | null>(null)
  const [xml, setXml] = useState('')
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [notice, setNotice] = useState('')
  const [assistantInput, setAssistantInput] = useState('')
  const [messages, setMessages] = useState<AssistantMessage[]>([
    {
      id: 'welcome',
      role: 'assistant',
      text: 'Я собрал черновик из описания. Проверьте порядок действий и добавьте роли, если знаете их.',
    },
  ])
  const panelRef = useRef<HTMLElement>(null)
  const editorRef = useRef<DiagramEditorHandle>(null)
  const localMode = projectId.startsWith('local-') || Boolean(local)

  const loadProject = useCallback(async () => {
    const stored = getLocalProject(projectId)
    if (stored) {
      setLocal(stored)
      setXml(stored.xml)
      setProject({ id: stored.id, title: stored.title })
      setLoading(false)
      return
    }
    try {
      const loaded = await api<ProjectInfo>(`/projects/${projectId}`)
      setProject(loaded)
      if (loaded.latest_version?.id) {
        const version = await api<{ xml: string }>(`/versions/${loaded.latest_version.id}`)
        setXml(version.xml)
      }
    } catch {
      setNotice('Не удалось связаться с backend. Создайте локальный черновик с главной страницы.')
    } finally {
      setLoading(false)
    }
  }, [projectId])

  useEffect(() => {
    void loadProject()
  }, [loadProject])

  useEffect(() => {
    const runId = sessionStorage.getItem(`arkhitektor:run:${projectId}`)
    if (!runId) return
    const stream = new EventSource(`/api/v1/runs/${runId}/events`)
    stream.addEventListener('stage', (event) => {
      const data = JSON.parse((event as MessageEvent<string>).data) as {
        data?: { label?: string; progress?: number }
      }
      setNotice(
        `${data.data?.label ?? 'Собираем схему'}${data.data?.progress ? ` / ${Math.round(data.data.progress * 100)}%` : ''}`,
      )
    })
    stream.addEventListener('done', () => {
      stream.close()
      sessionStorage.removeItem(`arkhitektor:run:${projectId}`)
      setNotice('Черновик собран. Проверьте схему и вопросы к источнику.')
      void loadProject()
    })
    stream.addEventListener('error', () => {
      stream.close()
      setNotice('Прогон завершился с ошибкой. Попробуйте запустить сборку ещё раз.')
    })
    return () => stream.close()
  }, [loadProject, projectId])

  const openQuestions = useMemo(
    () => project?.questions?.filter((question) => question.status === 'open') ?? [],
    [project],
  )
  const firstQuestion = openQuestions[0]

  const handleReady = useCallback((handle: DiagramEditorHandle) => {
    editorRef.current = handle
    handle.setPropertiesPanel(panelRef.current)
    window.setTimeout(() => handle.fit(), 80)
  }, [])

  const saveXml = useCallback(
    (next: string) => {
      setXml(next)
      const currentLocal = getLocalProject(projectId)
      if (currentLocal) {
        const updated = { ...currentLocal, xml: next }
        setLocal(updated)
        saveLocalProject(updated)
      }
    },
    [projectId],
  )

  async function saveVersion() {
    if (!editorRef.current) return
    setSaving(true)
    try {
      const currentXml = await editorRef.current.exportXml()
      if (localMode) {
        saveXml(currentXml)
        setNotice('Изменения сохранены в этом браузере.')
      } else {
        const version = await api<{ number: number }>(`/projects/${projectId}/diagram`, {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ xml: currentXml }),
        })
        setNotice(`Сохранена версия ${version.number}.`)
        await loadProject()
      }
    } catch {
      setNotice('Не удалось сохранить версию. Скачайте BPMN-файл, чтобы не потерять работу.')
    } finally {
      setSaving(false)
    }
  }

  async function download() {
    const currentXml = await editorRef.current?.exportXml()
    if (!currentXml) return
    const blob = new Blob([currentXml], { type: 'application/xml' })
    const url = URL.createObjectURL(blob)
    const anchor = document.createElement('a')
    anchor.href = url
    anchor.download = `${(project?.title || 'process').replace(/[^\p{L}\p{N}-]+/gu, '-')}.bpmn`
    anchor.click()
    URL.revokeObjectURL(url)
  }

  async function runAgain() {
    try {
      const run = await api<{ id: string }>(`/projects/${projectId}/runs`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ mode: 'analyze' }),
      })
      sessionStorage.setItem(`arkhitektor:run:${projectId}`, run.id)
      setNotice('Запускаем анализ источников…')
      window.location.reload()
    } catch {
      setNotice('Для анализа нужен запущенный backend. Сейчас открыт локальный редактор.')
    }
  }

  function sendMessage() {
    if (!assistantInput.trim()) return
    setMessages((current) => [
      ...current,
      { id: crypto.randomUUID(), role: 'user', text: assistantInput.trim() },
    ])
    setAssistantInput('')
    setNotice(
      'Сообщение сохранено в черновике. Подключение диалога к реальной LLM ещё не включено в серверной заглушке.',
    )
  }

  if (loading)
    return (
      <main className="grid min-h-dvh place-items-center bg-bg text-sm text-fg-muted">
        Открываем проект…
      </main>
    )

  return (
    <main className="studio-shell flex h-dvh min-h-[720px] flex-col overflow-hidden bg-bg text-fg">
      <header className="flex h-12 shrink-0 items-center justify-between border-b border-border bg-surface px-4">
        <div className="flex min-w-0 items-center gap-3">
          <a
            href="/"
            className="flex items-center gap-2 text-sm font-semibold text-fg no-underline"
          >
            <span className="brand-mark">
              <Icon name="diagram" size={16} />
            </span>
            Архитектор
          </a>
          <span className="text-fg-subtle">/</span>
          <span className="truncate text-sm font-medium">{project?.title ?? 'Новый процесс'}</span>
          <span className="rounded border border-border px-1.5 py-0.5 text-2xs text-fg-subtle">
            {localMode ? 'Локальный черновик' : 'BPMN 2.0'}
          </span>
        </div>
        <div className="flex items-center gap-2">
          <span className="hidden max-w-64 truncate text-xs text-fg-muted xl:inline" role="status">
            {notice}
          </span>
          <Button size="sm" variant="ghost" leadingIcon="refresh" onClick={runAgain}>
            Проверить источники
          </Button>
          <Button
            size="sm"
            variant="secondary"
            leadingIcon="download"
            onClick={() => void download()}
          >
            Скачать BPMN
          </Button>
          <Button
            size="sm"
            variant="primary"
            leadingIcon="check"
            loading={saving}
            onClick={saveVersion}
          >
            Сохранить
          </Button>
        </div>
      </header>

      <div className="studio-content grid min-h-0 flex-1 grid-cols-[250px_minmax(380px,1fr)_320px]">
        <aside className="flex min-h-0 flex-col border-r border-border bg-bg-subtle">
          <div className="border-b border-border p-4">
            <div className="mb-3 flex items-center justify-between">
              <h2 className="text-xs font-semibold">Источники</h2>
              <IconButton
                size="sm"
                icon="plus"
                label="Добавить источник"
                tooltip={false}
                onClick={() => setNotice('Добавление нового источника появится в следующем шаге.')}
              />
            </div>
            <div className="rounded-md border border-border bg-surface p-3">
              <div className="mb-1 flex items-center gap-2 text-xs font-medium">
                <Icon name="file-text" size={16} className="text-accent-fg" />{' '}
                {local?.source ? 'Описание процесса' : 'Регламент'}
              </div>
              <p className="line-clamp-3 text-xs leading-5 text-fg-muted">
                {local?.source ||
                  project?.description ||
                  'Материалы проекта будут отображаться здесь.'}
              </p>
              <div className="mt-2 flex items-center gap-1.5 text-2xs text-success-fg">
                <Icon name="check" size={14} /> Источник добавлен
              </div>
            </div>
          </div>
          <ScrollArea className="min-h-0 flex-1" viewportClassName="p-4">
            <div className="mb-3 flex items-center justify-between">
              <h2 className="text-xs font-semibold">Уточнить</h2>
              <span className="rounded-full bg-amber-subtle px-2 py-0.5 text-2xs text-amber-fg">
                {openQuestions.length || (localMode ? 1 : 0)}
              </span>
            </div>
            {openQuestions.length > 0 ? (
              openQuestions.map((question) => (
                <Button
                  key={question.id}
                  size="md"
                  variant="secondary"
                  onClick={() =>
                    question.element_ids[0] && editorRef.current?.focusElement(question.element_ids)
                  }
                  className="mb-2 h-auto w-full whitespace-normal rounded-md border-amber/25 bg-amber-subtle p-3 text-left hover:border-amber/50"
                >
                  <span className="block w-full">
                    <span className="mb-1 block text-2xs font-medium text-amber-fg">
                      {question.code} / важно
                    </span>
                    <span className="block text-xs leading-5">{question.text}</span>
                    <span className="mt-2 block text-2xs leading-4 text-fg-muted">
                      Если пропустить: {question.assumption}
                    </span>
                  </span>
                </Button>
              ))
            ) : localMode ? (
              <Card padding="sm" className="border-amber/25 bg-amber-subtle">
                <p className="text-xs leading-5">
                  Кто выполняет каждый шаг? Добавьте роли в описание, затем пересоберите схему.
                </p>
              </Card>
            ) : (
              <p className="text-xs leading-5 text-fg-muted">
                После анализа появятся вопросы к неполным или противоречивым сведениям.
              </p>
            )}
            <div className="mt-5 rounded-md border border-border bg-surface p-3">
              <h3 className="mb-2 flex items-center gap-1.5 text-xs font-medium">
                <Icon name="shield-check" size={14} /> Проверка схемы
              </h3>
              <div className="flex items-center justify-between text-xs text-fg-muted">
                <span>Формат BPMN</span>
                <span
                  className={
                    project?.latest_version?.report.xsd_valid ? 'text-success-fg' : 'text-fg-subtle'
                  }
                >
                  {project?.latest_version
                    ? project.latest_version.report.xsd_valid
                      ? 'Корректен'
                      : 'Есть ошибки'
                    : 'Черновик'}
                </span>
              </div>
              <div className="mt-2 flex items-center justify-between text-xs text-fg-muted">
                <span>Замечания</span>
                <span>{project?.latest_version?.report.lint.length ?? 'Не запускалась'}</span>
              </div>
            </div>
          </ScrollArea>
          <div className="border-t border-border p-3 text-2xs text-fg-subtle">
            {localMode
              ? 'Локальная демо-сборка / без LLM'
              : `Версия ${project?.latest_version?.number ?? 'ещё не создана'}`}
          </div>
        </aside>

        <section className="flex min-h-0 min-w-0 flex-col bg-surface">
          <div className="flex h-10 shrink-0 items-center justify-between border-b border-border px-4">
            <div className="flex items-center gap-2 text-xs">
              <Icon name="diagram" size={16} className="text-fg-muted" /> Процесс
            </div>
            <div className="flex items-center gap-1 text-fg-muted">
              <IconButton
                size="sm"
                icon="zoom-out"
                label="Уменьшить"
                tooltip={false}
                onClick={() => editorRef.current?.zoomOut()}
              />
              <IconButton
                size="sm"
                icon="fit-view"
                label="Вписать схему"
                tooltip={false}
                onClick={() => editorRef.current?.fit()}
              />
              <IconButton
                size="sm"
                icon="zoom-in"
                label="Увеличить"
                tooltip={false}
                onClick={() => editorRef.current?.zoomIn()}
              />
            </div>
          </div>
          {notice && (
            <div className="border-b border-border bg-accent-subtle px-4 py-2 text-xs text-accent-fg">
              {notice}
            </div>
          )}
          <div className="relative min-h-0 flex-1">
            {xml ? (
              <LazyDiagramEditor
                ref={editorRef}
                xml={xml}
                onChange={saveXml}
                onReady={handleReady}
                className="h-full w-full"
                ariaLabel="Редактор BPMN процесса"
              />
            ) : (
              <div className="grid h-full place-items-center p-10 text-center">
                <div>
                  <Icon name="circle-dashed" size={24} className="mx-auto mb-3 text-accent" />
                  <h2 className="mb-1 text-sm font-medium">
                    {project?.active_run?.stage_label || 'Схема ещё не собрана'}
                  </h2>
                  <p className="max-w-sm text-xs leading-5 text-fg-muted">
                    {notice || 'Запустите проверку источников, чтобы получить BPMN-черновик.'}
                  </p>
                  <Button className="mt-4" variant="primary" leadingIcon="bolt" onClick={runAgain}>
                    Собрать черновик
                  </Button>
                </div>
              </div>
            )}
          </div>
        </section>

        <aside className="flex min-h-0 flex-col border-l border-border bg-surface">
          <div className="flex h-10 shrink-0 items-center justify-between border-b border-border px-4">
            <h2 className="flex items-center gap-2 text-xs font-semibold">
              <Icon name="messages" size={16} className="text-accent-fg" /> Помощник по процессу
            </h2>
            <span className="rounded border border-border px-1.5 py-0.5 text-2xs text-fg-subtle">
              прототип
            </span>
          </div>
          <ScrollArea className="min-h-0 flex-1" viewportClassName="p-4">
            <div className="mb-4 rounded-lg border border-border bg-bg-subtle p-3 text-xs leading-5 text-fg-muted">
              Я помогу разобрать процесс и найти пропуски. Уточните шаг, роль или условие — ответ
              сохранится как заметка к черновику.
            </div>
            {messages.map((message) => (
              <div
                key={message.id}
                className={`mb-3 max-w-[92%] rounded-lg px-3 py-2 text-xs leading-5 ${message.role === 'assistant' ? 'border border-border bg-surface text-fg-muted' : 'ml-auto bg-accent-subtle text-accent-fg'}`}
              >
                {message.text}
              </div>
            ))}
            {firstQuestion && (
              <Button
                size="sm"
                variant="secondary"
                onClick={() => setAssistantInput(firstQuestion.text)}
                className="mb-3 h-auto whitespace-normal rounded-full px-2.5 py-1.5 text-left text-2xs"
              >
                {firstQuestion.text}
              </Button>
            )}
          </ScrollArea>
          <div className="border-t border-border p-3">
            <Textarea
              value={assistantInput}
              onChange={(event) => setAssistantInput(event.target.value)}
              minRows={2}
              maxRows={5}
              placeholder="Напишите уточнение…"
              className="border-0 bg-bg-subtle shadow-none focus:ring-0"
            />
            <div className="mt-2 flex items-center justify-between">
              <span className="text-2xs text-fg-subtle">
                ИИ-ответы включатся после настройки backend
              </span>
              <Button
                size="sm"
                variant="primary"
                leadingIcon="send"
                onClick={sendMessage}
                aria-label="Добавить сообщение"
              >
                Отправить
              </Button>
            </div>
          </div>
        </aside>
      </div>
    </main>
  )
}
