import { createFileRoute, Link, useNavigate } from '@tanstack/react-router'
import { useState } from 'react'
import { ThemeSwitch } from '@/features/theme-switch/theme-switch'
import { Button, Card, Icon, Textarea } from '@/shared/ui'
import './home.css'

export const Route = createFileRoute('/')({ component: HomePage })

function HomePage() {
  const [brief, setBrief] = useState('')
  const navigate = useNavigate()

  function continueWithBrief() {
    const text = brief.trim()
    if (!text) return
    void navigate({ to: '/new', search: { text } })
  }

  return (
    <main className="home-shell min-h-dvh bg-bg text-fg">
      <aside className="home-sidebar" aria-label="Навигация по продукту">
        <Link to="/" className="home-brand no-underline">
          <span className="brand-mark">
            <Icon name="diagram" size={16} />
          </span>
          <span className="min-w-0">
            <span className="block text-sm font-semibold tracking-tight">Архитектор</span>
            <span className="block text-xs text-fg-subtle">BPMN-ассистент</span>
          </span>
        </Link>

        <div className="home-nav-group">
          <div className="home-nav-label">Рабочее пространство</div>
          <Link to="/" className="home-nav-item" activeProps={{ 'aria-current': 'page' }}>
            <Icon name="home" size={16} />
            Главная
          </Link>
          <Link to="/projects" className="home-nav-item">
            <Icon name="folder" size={16} />
            Проекты
          </Link>
          <Link to="/new" className="home-nav-item">
            <Icon name="plus" size={16} />
            Новый процесс
          </Link>
          <Link to="/new" search={{ example: 'tp861' }} className="home-nav-item">
            <Icon name="file-text" size={16} />
            Пример процесса
          </Link>
        </div>

        <div className="home-sidebar-bottom">
          <div className="home-nav-label">Изучить продукт</div>
          <Link to="/dev/diagram" className="home-nav-item">
            <Icon name="diagram" size={16} />
            Редактор BPMN
          </Link>
          <Link to="/styleguide" className="home-nav-item">
            <Icon name="components" size={16} />
            Дизайн-система
          </Link>
          <div className="home-theme-row">
            <span className="text-xs text-fg-subtle">Тема</span>
            <ThemeSwitch compact />
          </div>
          <div className="home-sidebar-footnote">Локальный прототип BPMN 2.0</div>
        </div>
      </aside>

      <div className="home-main">
        <header className="home-topbar">
          <div className="flex items-center gap-2 text-xs text-fg-muted">
            <span>Архитектор</span>
            <Icon name="chevron-right" size={14} className="text-fg-subtle" />
            <span className="text-fg">Главная</span>
          </div>
          <div className="flex items-center gap-2">
            <Link to="/styleguide" className="home-topbar-link">
              Дизайн-система
            </Link>
            <Button asChild variant="primary" size="sm" leadingIcon="plus">
              <Link to="/new">Новый процесс</Link>
            </Button>
          </div>
        </header>

        <div className="home-content">
          <section className="home-hero" aria-labelledby="home-title">
            <div className="home-hero-copy">
              <div className="mb-4 flex items-center gap-2 text-xs text-fg-subtle">
                <span className="home-status-dot" />
                Ассистент для описания бизнес-процессов
              </div>
              <h1 id="home-title" className="type-display home-title">
                Из материалов —<br />в проверяемую схему.
              </h1>
              <p className="home-lead">
                Соберите регламент, заметки и договорённости в BPMN-процесс. Ассистент покажет
                неясности, отметит допущения и оставит схему редактируемой.
              </p>
              <div className="flex flex-wrap items-center gap-2.5">
                <Button asChild variant="primary" size="lg" trailingIcon="arrow-right">
                  <Link to="/new">Создать процесс</Link>
                </Button>
                <Button asChild variant="secondary" size="lg" leadingIcon="player-play">
                  <Link to="/new" search={{ example: 'tp861' }}>
                    Открыть пример
                  </Link>
                </Button>
              </div>
              <div className="mt-5 flex items-center gap-2 text-xs text-fg-subtle">
                <Icon name="shield-check" size={14} />
                Вы проверяете черновик до сохранения и экспорта
              </div>
            </div>

            <Card variant="elevated" padding="none" className="home-demo-card">
              <div className="home-demo-head">
                <div className="min-w-0">
                  <div className="text-xs text-fg-subtle">ДЕМО-ПРОЦЕСС</div>
                  <div className="mt-1 truncate text-sm font-medium">
                    Технологическое присоединение
                  </div>
                </div>
                <span className="home-demo-tag">
                  <Icon name="eye" size={14} /> Пример
                </span>
              </div>

              <div className="home-demo-body">
                <div
                  className="home-diagram"
                  role="img"
                  aria-label="Фрагмент BPMN: заявитель подаёт заявку, сетевая организация проверяет документы и направляет договор."
                >
                  <div className="home-diagram-toolbar">
                    <span className="flex items-center gap-1.5">
                      <Icon name="diagram" size={14} /> Процесс
                    </span>
                    <span className="home-diagram-zoom font-mono">Масштаб 100%</span>
                  </div>
                  <div className="home-lane">
                    <span className="home-lane-label">Заявитель</span>
                    <div className="home-flow-row">
                      <span className="home-flow-event" />
                      <span className="home-flow-edge" />
                      <span className="home-flow-task">Подать заявку</span>
                      <span className="home-flow-edge" />
                      <span className="home-flow-gateway" />
                    </div>
                  </div>
                  <div className="home-lane home-lane-second">
                    <span className="home-lane-label">Сетевая организация</span>
                    <div className="home-flow-row">
                      <span className="home-flow-task home-flow-task-active">
                        Проверить документы
                      </span>
                      <span className="home-flow-edge" />
                      <span className="home-flow-task">Направить договор</span>
                      <span className="home-flow-edge" />
                      <span className="home-flow-event home-flow-event-end" />
                    </div>
                  </div>
                  <div className="home-diagram-caption">
                    <span className="flex items-center gap-1.5">
                      <Icon name="circle-check" size={14} className="text-success" />
                      BPMN 2.0
                    </span>
                    <span>Схема проверяется перед экспортом</span>
                  </div>
                </div>

                <div className="home-demo-aside">
                  <div className="home-question">
                    <div className="mb-2 flex items-center justify-between gap-2">
                      <span className="flex items-center gap-1.5 text-xs font-medium text-amber-fg">
                        <Icon name="assumption" size={14} /> Нужно уточнить
                      </span>
                      <span className="text-2xs text-fg-subtle">Вопрос</span>
                    </div>
                    <p className="text-xs leading-5 text-fg">
                      Кто согласует заявку после проверки?
                    </p>
                    <div className="mt-2 border-t border-amber/20 pt-2 text-2xs leading-4 text-amber-fg">
                      Связано с фрагментом источника
                    </div>
                  </div>
                  <div className="home-source-list">
                    <div className="mb-2 flex items-center gap-1.5 text-xs font-medium">
                      <Icon name="file-text" size={14} className="text-accent-fg" /> Источники
                    </div>
                    <div className="home-source-row">Регламент ТП, 12 стр.</div>
                    <div className="home-source-row">Заметка со встречи, голосовая</div>
                  </div>
                </div>
              </div>
              <div className="home-demo-footer">
                <span>Схема, вопросы и материалы — в одном проекте</span>
                <Link to="/new" search={{ example: 'tp861' }} className="home-inline-link">
                  Разобрать пример <Icon name="arrow-right" size={14} />
                </Link>
              </div>
            </Card>
          </section>

          <section className="home-create" aria-labelledby="home-create-title">
            <div className="home-section-intro">
              <div className="home-eyebrow">Первый шаг</div>
              <h2 id="home-create-title" className="type-title mt-2">
                Начните с короткого описания
              </h2>
              <p className="mt-2 max-w-[330px] text-sm leading-6 text-fg-muted">
                Напишите, как процесс устроен сейчас. Файлы и голос можно добавить на следующем
                шаге.
              </p>
            </div>
            <Card variant="elevated" padding="md" className="home-brief-card">
              <label htmlFor="home-brief" className="mb-2 block text-xs font-medium text-fg-muted">
                Что происходит в процессе?
              </label>
              <Textarea
                id="home-brief"
                value={brief}
                onChange={(event) => setBrief(event.target.value)}
                onKeyDown={(event) => {
                  if ((event.metaKey || event.ctrlKey) && event.key === 'Enter') continueWithBrief()
                }}
                minRows={3}
                maxRows={5}
                placeholder="Например: заявитель подаёт заявку, оператор проверяет документы и просит дополнить их, если чего-то не хватает…"
                className="px-3 py-3 text-sm leading-6"
              />
              <div className="mt-3 flex items-center justify-between gap-4">
                <span className="text-xs text-fg-subtle">
                  {brief.length > 0
                    ? `${brief.length.toLocaleString('ru-RU')} знаков`
                    : 'Текст можно изменить позже'}
                </span>
                <Button
                  variant="primary"
                  size="md"
                  trailingIcon="arrow-right"
                  disabled={!brief.trim()}
                  onClick={continueWithBrief}
                >
                  Продолжить
                </Button>
              </div>
            </Card>
          </section>

          <section className="home-capabilities" aria-labelledby="home-capabilities-title">
            <div className="home-section-heading">
              <div>
                <div className="home-eyebrow">Внутри проекта</div>
                <h2 id="home-capabilities-title" className="type-title mt-2">
                  Путь от источников к BPMN
                </h2>
              </div>
              <Link to="/styleguide" className="home-inline-link">
                Принципы интерфейса <Icon name="arrow-right" size={14} />
              </Link>
            </div>
            <div className="home-capability-grid">
              <Card variant="outline" padding="md" className="home-capability">
                <span className="home-capability-icon">
                  <Icon name="file-text" size={16} />
                </span>
                <div className="mt-4 text-sm font-semibold">Соберите материалы</div>
                <p className="mt-1 text-xs leading-5 text-fg-muted">
                  Текст, документы и голосовые заметки остаются рядом со схемой.
                </p>
              </Card>
              <Card variant="outline" padding="md" className="home-capability">
                <span className="home-capability-icon home-capability-icon-amber">
                  <Icon name="messages" size={16} />
                </span>
                <div className="mt-4 text-sm font-semibold">Разберите неясности</div>
                <p className="mt-1 text-xs leading-5 text-fg-muted">
                  Вопросы, цитаты и допущения помогают проверить ход процесса.
                </p>
              </Card>
              <Card variant="outline" padding="md" className="home-capability">
                <span className="home-capability-icon home-capability-icon-success">
                  <Icon name="diagram" size={16} />
                </span>
                <div className="mt-4 text-sm font-semibold">Отредактируйте схему</div>
                <p className="mt-1 text-xs leading-5 text-fg-muted">
                  BPMN 2.0 можно проверить, поправить в редакторе и скачать.
                </p>
              </Card>
            </div>
          </section>

          <footer className="home-footer">
            <span>Архитектор BPMN. Рабочий прототип.</span>
            <Link to="/dev/diagram" className="home-footer-link">
              Открыть редактор <Icon name="arrow-up-right" size={14} />
            </Link>
          </footer>
        </div>
      </div>
    </main>
  )
}
