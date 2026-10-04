import { createFileRoute } from '@tanstack/react-router'
import { useEffect, useRef, useState } from 'react'
import { transcribeAudio } from '@/features/voice-transcription'
import { api, errorMessage, postForm, unwrap } from '@/shared/api/client'
import { Button, Card, FileInput, Icon, Input, Textarea } from '@/shared/ui'
import './home.css'

interface NewSearch {
  text?: string
  example?: string
}

export const Route = createFileRoute('/new')({
  validateSearch: (search: Record<string, unknown>): NewSearch => ({
    text: typeof search.text === 'string' ? search.text : undefined,
    example: typeof search.example === 'string' ? search.example : undefined,
  }),
  component: NewProjectPage,
})

const exampleText =
  'Заявитель подаёт заявку на технологическое присоединение. Сетевая организация проверяет комплектность документов. Если документов не хватает, она просит заявителя дополнить заявку. После проверки организация направляет договор и технические условия. Заявитель и сетевая организация выполняют свои мероприятия. Затем специалисты осматривают объект, подписывают акт и подключают объект к электросети.'

type VoiceState = 'idle' | 'recording' | 'transcribing'

function NewProjectPage() {
  const search = Route.useSearch()
  const [title, setTitle] = useState(search.example ? 'Технологическое присоединение' : '')
  const [source, setSource] = useState(search.example ? exampleText : (search.text ?? ''))
  const [file, setFile] = useState<File | null>(null)
  const [working, setWorking] = useState(false)
  const [notice, setNotice] = useState('')
  const [voiceState, setVoiceState] = useState<VoiceState>('idle')
  const fileRef = useRef<HTMLInputElement>(null)
  const recorderRef = useRef<MediaRecorder | null>(null)
  const streamRef = useRef<MediaStream | null>(null)
  const audioChunksRef = useRef<Blob[]>([])

  useEffect(
    () => () => {
      recorderRef.current?.stream?.getTracks().forEach((track) => {
        track.stop()
      })
      streamRef.current?.getTracks().forEach((track) => {
        track.stop()
      })
    },
    [],
  )

  async function transcribeRecording(blob: Blob) {
    if (blob.size === 0) {
      setVoiceState('idle')
      setNotice('Запись пустая. Попробуйте ещё раз.')
      return
    }

    try {
      const result = await transcribeAudio(blob)
      setSource((current) => [current.trim(), result.text.trim()].filter(Boolean).join('\n'))
      setNotice('Расшифровка добавлена в описание. Проверьте текст перед сборкой схемы.')
    } catch {
      setNotice(
        'Не удалось расшифровать запись. Проверьте, что backend запущен и настроен на Deepgram.',
      )
    } finally {
      setVoiceState('idle')
    }
  }

  async function startRecording() {
    setNotice('')
    if (!navigator.mediaDevices?.getUserMedia || !window.MediaRecorder) {
      setNotice('Этот браузер не поддерживает запись аудио. Можно загрузить готовую расшифровку.')
      return
    }

    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
      streamRef.current = stream
      audioChunksRef.current = []
      const recorder = new MediaRecorder(stream)
      recorderRef.current = recorder
      recorder.ondataavailable = (event) => {
        if (event.data.size > 0) audioChunksRef.current.push(event.data)
      }
      recorder.onstop = () => {
        const blob = new Blob(audioChunksRef.current, {
          type: recorder.mimeType || 'audio/webm',
        })
        audioChunksRef.current = []
        stream.getTracks().forEach((track) => {
          track.stop()
        })
        streamRef.current = null
        void transcribeRecording(blob)
      }
      recorder.onerror = () => {
        stream.getTracks().forEach((track) => {
          track.stop()
        })
        streamRef.current = null
        setVoiceState('idle')
        setNotice('Запись прервалась. Проверьте микрофон и попробуйте ещё раз.')
      }
      recorder.start()
      setVoiceState('recording')
      setNotice('Идёт запись. Нажмите «Остановить запись», когда закончите.')
    } catch {
      streamRef.current?.getTracks().forEach((track) => {
        track.stop()
      })
      streamRef.current = null
      setVoiceState('idle')
      setNotice('Нет доступа к микрофону. Разрешите его для этой страницы и попробуйте ещё раз.')
    }
  }

  function stopRecording() {
    const recorder = recorderRef.current
    if (!recorder || recorder.state === 'inactive') return
    setVoiceState('transcribing')
    setNotice('Расшифровываем запись…')
    recorder.stop()
  }

  async function createProject() {
    if (!source.trim() && !file) {
      setNotice('Добавьте описание или документ, чтобы собрать черновик.')
      return
    }
    setWorking(true)
    setNotice('Создаём проект и собираем первый черновик…')
    const projectTitle = title.trim() || 'Новый процесс'
    let projectId: string | undefined
    try {
      const project =
        search.example === 'tp861'
          ? unwrap(
              await api.POST('/api/v1/projects/from-example', {
                body: { example_id: 'tp861' },
              }),
            )
          : unwrap(
              await api.POST('/api/v1/projects', {
                body: {
                  title: projectTitle,
                  description: source.trim().slice(0, 500) || null,
                },
              }),
            )
      projectId = project.id
      if (source.trim() && search.example !== 'tp861') {
        unwrap(
          await api.POST('/api/v1/projects/{project_id}/sources/text', {
            params: { path: { project_id: projectId } },
            body: { content: source.trim(), kind: 'text', title: 'Описание процесса' },
          }),
        )
      }
      if (file) {
        const form = new FormData()
        form.append('file', file)
        form.append('title', file.name)
        await postForm(`/api/v1/projects/${projectId}/sources/file`, form)
      }
      const run = unwrap(
        await api.POST('/api/v1/projects/{project_id}/runs', {
          params: { path: { project_id: projectId } },
          body: { mode: 'build' },
        }),
      )
      sessionStorage.setItem(`arkhitektor:run:${projectId}`, run.id)
    } catch (error) {
      if (projectId) {
        // Проект уже создан на backend: открываем его штатное рабочее место даже при ошибке прогона.
        window.location.assign(`/projects/${projectId}`)
        return
      }
      setNotice(errorMessage(error, 'Не удалось создать проект на сервере.'))
      setWorking(false)
      return
    }
    window.location.assign(`/projects/${projectId}`)
  }

  async function fillExample() {
    setTitle('Технологическое присоединение')
    setSource(exampleText)
    setNotice('Добавлен короткий пример. Можно отредактировать текст перед сборкой.')
  }

  return (
    <main className="min-h-dvh bg-bg text-fg">
      <header className="mx-auto flex max-w-[1120px] items-center justify-between px-8 py-5">
        <a
          href="/"
          className="flex items-center gap-2.5 text-sm font-semibold text-fg no-underline"
        >
          <span className="brand-mark">
            <Icon name="diagram" size={16} />
          </span>
          Архитектор <span className="text-fg-subtle">/ Новый процесс</span>
        </a>
        <a
          href="/"
          className="inline-flex items-center gap-1.5 text-sm text-fg-muted no-underline hover:text-fg"
        >
          <Icon name="arrow-left" size={16} /> На главную
        </a>
      </header>
      <div className="mx-auto grid max-w-[1120px] grid-cols-[1fr_300px] gap-12 px-8 pb-20 pt-8">
        <section>
          <div className="mb-3 text-xs font-medium uppercase tracking-widest text-fg-subtle">
            Новый проект
          </div>
          <h1 className="mb-3 text-3xl font-semibold tracking-tight">С чего начнём?</h1>
          <p className="mb-8 max-w-[620px] text-sm leading-6 text-fg-muted">
            Опишите процесс так, как рассказываете коллеге. Позже мы поможем выделить роли, порядок
            действий и места, где нужны уточнения.
          </p>

          <Card padding="lg" variant="elevated">
            <label htmlFor="project-title" className="mb-2 block text-xs font-medium text-fg-muted">
              Название процесса
            </label>
            <Input
              id="project-title"
              value={title}
              onChange={(event) => setTitle(event.target.value)}
              placeholder="Например, согласование договора"
              wrapperClassName="mb-6"
            />
            <div className="mb-2 flex items-center justify-between">
              <label htmlFor="process-source" className="text-xs font-medium text-fg-muted">
                Описание или текст источника
              </label>
              <span className="text-xs text-fg-subtle">
                {source.length.toLocaleString('ru-RU')} знаков
              </span>
            </div>
            <Textarea
              id="process-source"
              value={source}
              onChange={(event) => setSource(event.target.value)}
              minRows={8}
              maxRows={16}
              placeholder="Кто начинает процесс? Что происходит дальше? Где принимают решение? Чем всё заканчивается?"
              className="px-3 py-3 text-sm leading-6"
            />
            <div className="mt-3 flex flex-wrap items-center gap-2">
              <Button
                size="sm"
                variant="secondary"
                leadingIcon="file-upload"
                onClick={() => fileRef.current?.click()}
              >
                {file ? file.name : 'Прикрепить документ'}
              </Button>
              <FileInput
                ref={fileRef}
                accept=".pdf,.docx,.md,.txt,.csv,application/pdf,text/csv"
                onChange={(event) => setFile(event.target.files?.[0] ?? null)}
              />
              <Button
                size="sm"
                variant={voiceState === 'recording' ? 'secondary' : 'ghost'}
                leadingIcon={voiceState === 'recording' ? 'player-stop' : 'microphone'}
                loading={voiceState === 'transcribing'}
                disabled={working || voiceState === 'transcribing'}
                onClick={voiceState === 'recording' ? stopRecording : startRecording}
              >
                {voiceState === 'recording'
                  ? 'Остановить запись'
                  : voiceState === 'transcribing'
                    ? 'Расшифровываем…'
                    : 'Надиктовать'}
              </Button>
              {file && (
                <Button size="sm" variant="ghost" className="ml-auto" onClick={() => setFile(null)}>
                  Убрать файл
                </Button>
              )}
            </div>
            <div className="mt-6 flex items-center justify-between border-t border-border pt-5">
              <Button size="sm" variant="ghost" leadingIcon="plus" onClick={fillExample}>
                Заполнить примером
              </Button>
              <Button
                variant="primary"
                size="lg"
                trailingIcon="arrow-right"
                loading={working}
                disabled={voiceState !== 'idle'}
                onClick={createProject}
              >
                Собрать черновик
              </Button>
            </div>
            {notice && (
              <p role="status" className="mt-4 text-xs leading-5 text-fg-muted">
                {notice}
              </p>
            )}
          </Card>
          <p className="mt-4 flex items-center gap-2 text-xs text-fg-subtle">
            <Icon name="check" size={16} className="text-success" /> Черновик можно поправить до
            проверки и скачивания
          </p>
        </section>

        <aside className="pt-12">
          <Card padding="md" className="mb-3">
            <div className="mb-3 flex size-8 items-center justify-center rounded-md bg-accent-subtle text-accent-fg">
              <Icon name="assumption" size={16} />
            </div>
            <h2 className="mb-2 text-sm font-semibold">Не нужно писать идеально</h2>
            <p className="text-xs leading-5 text-fg-muted">
              Сначала добавьте известные шаги. Если не хватает исполнителя или условия, система
              задаст вопрос и покажет фрагмент, который его вызвал.
            </p>
          </Card>
          <Card padding="md" className="mb-3">
            <div className="mb-3 flex size-8 items-center justify-center rounded-md bg-bg-subtle text-fg-muted">
              <Icon name="file-text" size={16} />
            </div>
            <h2 className="mb-2 text-sm font-semibold">Подойдут готовые материалы</h2>
            <p className="text-xs leading-5 text-fg-muted">
              Регламент, инструкция, заметки со встречи или расшифровка. Текст источника останется в
              проекте для проверки схемы.
            </p>
          </Card>
          <Card padding="md" className="border-amber/25 bg-amber-subtle">
            <h2 className="mb-2 text-xs font-semibold text-amber-fg">Демо-режим</h2>
            <p className="text-xs leading-5 text-fg-muted">
              Если backend не запущен, схема соберётся локально из предложений. В ней не будет
              анализа ИИ, но её можно редактировать и скачать.
            </p>
          </Card>
        </aside>
      </div>
    </main>
  )
}
