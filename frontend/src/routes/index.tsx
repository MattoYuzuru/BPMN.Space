import { createFileRoute, Link, useNavigate } from '@tanstack/react-router'
import { useState } from 'react'
import { Button, Card, Icon, Textarea } from '@/shared/ui'
import './home.css'

export const Route = createFileRoute('/')({ component: HomePage })

function HomePage() {
  const [brief, setBrief] = useState('')
  const navigate = useNavigate()

  return (
    <main className="home-page min-h-dvh bg-bg text-fg">
      <header className="home-nav mx-auto flex max-w-[1240px] items-center justify-between px-8 py-5">
        <Link to="/" className="flex items-center gap-2.5 no-underline text-fg">
          <span className="brand-mark">
            <Icon name="diagram" size={16} />
          </span>
          <span className="font-semibold tracking-tight">Архитектор</span>
          <span className="rounded border border-border px-1.5 py-0.5 text-2xs text-fg-subtle">
            BPMN
          </span>
        </Link>
        <div className="flex items-center gap-5">
          <a href="#how" className="text-sm text-fg-muted no-underline hover:text-fg">
            Как это работает
          </a>
          <a href="/styleguide" className="text-sm text-fg-muted no-underline hover:text-fg">
            Дизайн-система
          </a>
          <Link to="/new" className="text-sm text-fg-muted no-underline hover:text-fg">
            Мои проекты
          </Link>
        </div>
      </header>

      <section className="home-hero mx-auto grid max-w-[1240px] grid-cols-[1.02fr_.98fr] items-center gap-14 px-8 pb-24 pt-14">
        <div className="max-w-[560px]">
          <div className="mb-5 inline-flex items-center gap-2 rounded-full border border-border bg-surface px-3 py-1.5 text-xs text-fg-muted">
            <span className="size-1.5 rounded-full bg-success" />
            BPMN 2.0 / с проверкой и источниками
          </div>
          <h1 className="type-display mb-5 leading-tight tracking-tighter">
            Из описания —<br />в ясный процесс.
          </h1>
          <p className="mb-8 max-w-[500px] text-base leading-7 text-fg-muted">
            Соберите регламент, заметки и устные договорённости в одну редактируемую BPMN-схему. Мы
            покажем неясности и поможем ничего не додумывать молча.
          </p>
          <div className="flex flex-wrap items-center gap-3">
            <Button asChild variant="primary" size="lg" trailingIcon="arrow-right">
              <Link to="/new">Создать процесс</Link>
            </Button>
            <Link
              to="/new"
              search={{ example: 'tp861' }}
              className="inline-flex h-10 items-center gap-2 rounded-md px-3 text-sm font-medium text-fg-muted no-underline transition hover:bg-hover hover:text-fg"
            >
              <Icon name="bolt" size={16} /> Посмотреть на примере
            </Link>
          </div>
          <div className="mt-8 flex items-center gap-2 text-xs text-fg-subtle">
            <Icon name="shield-check" size={16} />
            Черновик можно проверить и поправить до экспорта
          </div>
        </div>

        <div className="hero-preview relative rounded-xl border border-border bg-surface p-5 shadow-sm">
          <div className="mb-5 flex items-center justify-between border-b border-border pb-4">
            <div>
              <div className="text-xs text-fg-subtle">НОВЫЙ ПРОЕКТ</div>
              <div className="mt-1 text-sm font-medium">Технологическое присоединение</div>
            </div>
            <span className="inline-flex items-center gap-1.5 rounded-full bg-accent-subtle px-2.5 py-1 text-xs font-medium text-accent-fg">
              <span className="size-1.5 rounded-full bg-accent" /> Черновик
            </span>
          </div>
          <div className="preview-body grid grid-cols-[1fr_175px] gap-4">
            <div className="diagram-preview rounded-lg border border-border bg-bg-subtle p-5">
              <div className="mb-5 flex items-center gap-2 text-2xs text-fg-subtle">
                <span className="size-2 rounded-full border border-success" /> Схема процесса
              </div>
              <div className="flow-row">
                <span className="flow-event" />
                <span className="flow-edge" />
                <span className="flow-task">Подать заявку</span>
                <span className="flow-edge" />
                <span className="flow-task flow-task-active">Проверить документы</span>
                <span className="flow-edge" />
                <span className="flow-gateway" />
              </div>
              <div className="flow-label">
                Заявитель <span>Сетевая организация</span>
              </div>
              <div className="flow-footer mt-6 flex items-center gap-2 border-t border-border pt-3 text-xs text-fg-muted">
                <Icon name="circle-check" size={16} className="text-success" />
                BPMN 2.0 / проверка структуры
              </div>
            </div>
            <aside className="flex flex-col gap-3">
              <div className="rounded-lg border border-amber/30 bg-amber-subtle p-3">
                <div className="mb-1 flex items-center gap-1.5 text-xs font-medium text-amber-fg">
                  <Icon name="assumption" size={14} /> Нужно уточнить
                </div>
                <p className="text-xs leading-5 text-fg-muted">
                  Кто согласует заявку после проверки?
                </p>
                <div className="mt-2 border-t border-amber/20 pt-2 text-2xs text-amber-fg">
                  Есть цитата из источника
                </div>
              </div>
              <div className="rounded-lg border border-border bg-surface p-3">
                <div className="mb-1 flex items-center gap-1.5 text-xs font-medium">
                  <Icon name="file-text" size={14} /> Источники
                </div>
                <p className="text-xs leading-5 text-fg-muted">Регламент, 4 страницы</p>
                <p className="text-xs leading-5 text-fg-muted">Заметка встречи, голос</p>
              </div>
            </aside>
          </div>
          <div className="pointer-events-none absolute -right-4 -top-4 rounded-full border border-border bg-surface p-2 shadow-sm">
            <Icon name="bolt" size={16} className="text-accent" />
          </div>
        </div>
      </section>

      <section className="home-start border-y border-border bg-bg-subtle">
        <div className="mx-auto grid max-w-[1240px] grid-cols-[.72fr_1.28fr] gap-12 px-8 py-16">
          <div className="pt-1">
            <div className="mb-3 text-xs font-medium uppercase tracking-widest text-fg-subtle">
              Начните с того, что есть
            </div>
            <h2 className="max-w-[370px] text-2xl font-semibold leading-tight tracking-tight">
              Не нужно знать BPMN, чтобы начать.
            </h2>
            <p className="mt-3 max-w-[360px] text-sm leading-6 text-fg-muted">
              Опишите привычный порядок работы. Участников и развилки можно уточнить позже.
            </p>
            <div className="mt-8 flex flex-col gap-3 text-sm text-fg-muted">
              <span className="flex items-center gap-2">
                <Icon name="file-text" size={16} /> Текст и регламенты
              </span>
              <span className="flex items-center gap-2">
                <Icon name="microphone" size={16} /> Голосовые заметки
              </span>
              <span className="flex items-center gap-2">
                <Icon name="upload" size={16} /> PDF, DOCX, TXT
              </span>
            </div>
          </div>
          <Card variant="elevated" padding="lg" className="home-composer">
            <div className="mb-3 flex items-center justify-between">
              <label htmlFor="home-brief" className="text-sm font-medium">
                Опишите процесс своими словами
              </label>
              <span className="text-xs text-fg-subtle">можно коротко</span>
            </div>
            <Textarea
              id="home-brief"
              value={brief}
              onChange={(event) => setBrief(event.target.value)}
              minRows={5}
              maxRows={8}
              placeholder="Например: заявитель подаёт заявку, оператор проверяет документы. Если чего-то не хватает — просит дополнить…"
              className="px-3.5 py-3 text-sm leading-6"
            />
            <div className="mt-4 flex items-center justify-between">
              <span className="text-xs text-fg-subtle">
                Текст можно дополнить файлами и голосом
              </span>
              <Button
                variant="primary"
                trailingIcon="arrow-right"
                disabled={!brief.trim()}
                onClick={() => void navigate({ to: '/new', search: { text: brief } })}
              >
                Продолжить
              </Button>
            </div>
          </Card>
        </div>
      </section>

      <section id="how" className="mx-auto max-w-[1240px] px-8 py-16">
        <div className="mb-8 flex items-end justify-between">
          <div>
            <div className="mb-2 text-xs font-medium uppercase tracking-widest text-fg-subtle">
              Понятный путь
            </div>
            <h2 className="text-2xl font-semibold tracking-tight">
              От материалов к проверяемой схеме
            </h2>
          </div>
          <Link
            to="/new"
            className="inline-flex items-center gap-2 text-sm font-medium text-accent-fg no-underline hover:underline"
          >
            Начать работу <Icon name="arrow-right" size={16} />
          </Link>
        </div>
        <div className="grid grid-cols-4 gap-3">
          {[
            ['01', 'Добавьте источники', 'Текст, голос или документ — можно начать с одного.'],
            ['02', 'Разберите неясности', 'Вопросы будут связаны с фрагментами источников.'],
            ['03', 'Соберите BPMN', 'Система подготовит схему и отметит допущения.'],
            [
              '04',
              'Проверьте и сохраните',
              'Отредактируйте диаграмму, проверьте её и скачайте файл.',
            ],
          ].map(([number, title, description]) => (
            <Card key={number} padding="md" className="journey-card min-h-36">
              <div className="mb-4 text-xs font-mono text-accent-fg">{number}</div>
              <h3 className="mb-1 text-sm font-semibold">{title}</h3>
              <p className="text-xs leading-5 text-fg-muted">{description}</p>
            </Card>
          ))}
        </div>
        <div className="mt-12 flex items-center justify-between border-t border-border pt-5 text-xs text-fg-subtle">
          <span>Архитектор BPMN / рабочий прототип</span>
          <span className="flex items-center gap-1.5">
            <Icon name="shield-check" size={14} /> Данные не отправляются в модель без вашего
            действия
          </span>
        </div>
      </section>
    </main>
  )
}
