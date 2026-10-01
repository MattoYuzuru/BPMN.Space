import { useEffect, useState } from 'react'
import {
  Avatar,
  Badge,
  type BadgeTone,
  Button,
  Card,
  CardHeader,
  Divider,
  EmptyState,
  IconButton,
  Progress,
  ScrollArea,
  Skeleton,
  SkeletonText,
  Stepper,
  type StepStatus,
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
  Tag,
  toast,
} from '@/shared/ui'
import { Caption, Section, Specimen, SpecimenGrid } from './kit'

const QUESTION_NUMBERS = Array.from({ length: 16 }, (_, i) => i + 1)
const TONES: BadgeTone[] = ['neutral', 'accent', 'amber', 'success', 'danger']
const TONE_LABEL: Record<BadgeTone, string> = {
  neutral: 'Черновик',
  accent: 'В работе',
  amber: 'Допущение',
  success: 'Решено',
  danger: 'Ошибка',
}

export function NavigationSection() {
  return (
    <Section
      id="navigation"
      eyebrow="14 Компоненты"
      title="Вкладки"
      lead="Tabs переключают разделы одной сущности. Под активной вкладкой — тонкая линия, которая мягко переезжает. Счётчик в вкладке — только если число помогает решить, куда идти."
    >
      <Specimen title="Tabs">
        <Tabs defaultValue="questions">
          <TabsList aria-label="Разделы проекта">
            <TabsTrigger value="sources" icon="file-text" count={3}>
              Источники
            </TabsTrigger>
            <TabsTrigger value="questions" icon="message-question" count={4}>
              Вопросы
            </TabsTrigger>
            <TabsTrigger value="versions" icon="history">
              Версии
            </TabsTrigger>
            <TabsTrigger value="report" icon="shield-check" disabled>
              Проверка
            </TabsTrigger>
          </TabsList>
          <TabsContent value="sources">
            <p className="type-ui text-fg-muted">Регламент ТП.docx, заметка со встречи, ответ.</p>
          </TabsContent>
          <TabsContent value="questions">
            <p className="type-ui text-fg-muted">Четыре открытых вопроса, один блокирует схему.</p>
          </TabsContent>
          <TabsContent value="versions">
            <p className="type-ui text-fg-muted">Четыре версии, последняя — ручная правка.</p>
          </TabsContent>
        </Tabs>
      </Specimen>
    </Section>
  )
}

export function StatusSection() {
  const [progress, setProgress] = useState(64)
  const [step, setStep] = useState(2)
  const statusOf = (index: number): StepStatus =>
    index < step ? 'complete' : index === step ? 'current' : 'upcoming'
  return (
    <Section
      id="status"
      eyebrow="15 Компоненты"
      title="Статусы и ход процесса"
      lead="Badge — неинтерактивная метка статуса. Tag — сущность, которую можно убрать. Stepper показывает этапы прогона, Progress — ход загрузки. Тон всегда несёт смысл."
    >
      <SpecimenGrid>
        <Specimen title="Badge" note="subtle и outline, точка статуса">
          <div className="flex flex-col gap-3">
            {(['subtle', 'outline'] as const).map((variant) => (
              <div key={variant} className="flex flex-wrap items-center gap-2">
                <span className="type-code w-16 text-fg-subtle">{variant}</span>
                {TONES.map((tone) => (
                  <Badge key={tone} tone={tone} variant={variant} dot={variant === 'outline'}>
                    {TONE_LABEL[tone]}
                  </Badge>
                ))}
              </div>
            ))}
            <div className="flex flex-wrap items-center gap-2">
              <span className="type-code w-16 text-fg-subtle">icon</span>
              <Badge tone="success" icon="circle-check">
                Решено 2
              </Badge>
              <Badge tone="accent" icon="message-question">
                Осталось 2
              </Badge>
              <Badge tone="amber" icon="assumption">
                Новых 1
              </Badge>
            </div>
          </div>
        </Specimen>
        <Specimen title="Tag и Avatar" note="источники, роли, дорожки">
          <div className="flex flex-col gap-4">
            <div className="flex flex-wrap gap-2">
              <Tag
                icon="file-text"
                onRemove={() => toast('Источник убран')}
                removeLabel="Убрать Регламент ТП.docx"
              >
                Регламент ТП.docx
              </Tag>
              <Tag icon="microphone">Заметка со встречи</Tag>
              <Tag variant="accent" icon="filter" onRemove={() => {}} removeLabel="Сбросить фильтр">
                Только блокирующие
              </Tag>
              <Tag variant="assumption" icon="assumption">
                Руководитель отдела
              </Tag>
            </div>
            <Divider />
            <div className="flex items-center gap-3">
              {[
                'Заявитель',
                'Сетевая организация',
                'Гарантирующий поставщик',
                'Финансовый отдел',
              ].map((name) => (
                <div key={name} className="flex items-center gap-2">
                  <Avatar name={name} />
                  <span className="type-caption text-fg-muted">{name}</span>
                </div>
              ))}
            </div>
          </div>
        </Specimen>
        <Specimen title="Stepper" note="ход прогона, текущий этап дышит">
          <div className="flex flex-col gap-5">
            <Stepper
              aria-label="Ход прогона"
              steps={[
                { id: 'read', title: 'Чтение источников', meta: '2 с' },
                {
                  id: 'analyze',
                  title: 'Анализ и вопросы',
                  description: 'Найдено 4 вопроса, 1 блокирует схему',
                  meta: '9 с',
                },
                { id: 'build', title: 'Сборка схемы', description: 'Дорожки и связи' },
                { id: 'validate', title: 'Проверка XSD и bpmnlint' },
              ].map((item, index) => ({
                ...item,
                status: statusOf(index),
                meta: index < step ? item.meta : undefined,
              }))}
            />
            <div className="flex gap-2">
              <Button size="sm" onClick={() => setStep((s) => (s >= 4 ? 0 : s + 1))}>
                Следующий этап
              </Button>
            </div>
            <Divider />
            <Stepper
              aria-label="Импорт документа"
              steps={[
                { id: 'upload', title: 'Загрузка', status: 'complete', meta: '1 с' },
                {
                  id: 'parse',
                  title: 'Извлечение текста',
                  status: 'error',
                  description: 'В PDF нет текстового слоя. Загрузите документ .docx.',
                },
              ]}
            />
          </div>
        </Specimen>
        <Specimen title="Progress" note="без значения — импульс тока">
          <div className="flex flex-col gap-5">
            <div className="flex flex-col gap-2">
              <div className="flex justify-between">
                <span className="type-ui text-fg">Финансы проекта.docx</span>
                <span className="type-caption text-fg-subtle" data-numeric>
                  {progress}%
                </span>
              </div>
              <Progress value={progress} label="Загрузка документа" />
            </div>
            <div className="flex flex-col gap-2">
              <span className="type-ui text-fg">Распознавание голоса</span>
              <Progress label="Распознавание голоса" size="md" />
            </div>
            <div className="flex flex-col gap-2">
              <span className="type-ui text-fg">Решено вопросов: 3 из 4</span>
              <Progress value={75} tone="success" label="Решено вопросов" />
            </div>
            <div>
              <Button size="sm" onClick={() => setProgress((p) => (p >= 100 ? 8 : p + 23))}>
                Продвинуть
              </Button>
            </div>
          </div>
        </Specimen>
      </SpecimenGrid>
    </Section>
  )
}

export function FeedbackSection() {
  const [loading, setLoading] = useState(true)
  useEffect(() => {
    if (!loading) return
    const timer = window.setTimeout(() => setLoading(false), 2400)
    return () => window.clearTimeout(timer)
  }, [loading])
  return (
    <Section
      id="feedback"
      eyebrow="16 Компоненты"
      title="Обратная связь"
      lead="Тост — о результате действия, в прошедшем времени. Скелетон повторяет форму будущего содержимого. Пустое состояние говорит, что здесь будет, и даёт одно действие."
    >
      <SpecimenGrid>
        <Specimen title="Toast" note="снизу справа, не больше трёх">
          <div className="flex flex-wrap gap-2">
            <Button
              onClick={() =>
                toast('Вопрос проигнорирован', { action: { label: 'Отменить', onClick: () => {} } })
              }
            >
              Обычный
            </Button>
            <Button
              onClick={() =>
                toast.success('Источник добавлен', {
                  description: 'Финансы проекта.docx, 12 страниц',
                })
              }
            >
              Успех
            </Button>
            <Button
              onClick={() =>
                toast.warning('Схема построена с допущениями', {
                  description: 'Осталось 2 открытых вопроса.',
                })
              }
            >
              Внимание
            </Button>
            <Button
              tone="danger"
              onClick={() =>
                toast.error('Не удалось распознать голос', {
                  description: 'Проверьте микрофон и запишите ещё раз.',
                  action: { label: 'Повторить', onClick: () => {} },
                })
              }
            >
              Ошибка
            </Button>
          </div>
        </Specimen>
        <Specimen title="Skeleton" note="вместо спиннера, aria-busy на контейнере">
          <div aria-busy={loading} className="flex flex-col gap-4">
            {loading ? (
              <>
                <div className="flex items-center gap-3">
                  <Skeleton className="size-8 rounded-md" />
                  <div className="flex flex-1 flex-col gap-2">
                    <Skeleton className="h-3.5 w-2/5" />
                    <Skeleton className="h-3 w-1/4" />
                  </div>
                </div>
                <SkeletonText lines={3} />
              </>
            ) : (
              <Card variant="sunken" padding="sm" className="animate-fade-in">
                <CardHeader
                  title="Кто согласует бюджет?"
                  description="Важный, из голосовой заметки"
                  icon="message-question"
                />
                <p className="type-ui mt-2 text-fg-muted">
                  В тексте сказано «бюджет согласуется», но не указано кем.
                </p>
              </Card>
            )}
            <div>
              <Button
                size="sm"
                variant="ghost"
                leadingIcon="refresh"
                onClick={() => setLoading(true)}
              >
                Загрузить снова
              </Button>
            </div>
          </div>
        </Specimen>
      </SpecimenGrid>
      <Specimen title="EmptyState" note="на сетке-подложке" bodyClassName="p-0">
        <div className="grid grid-cols-2 divide-x divide-border">
          <EmptyState
            icon="folder-plus"
            title="Проектов пока нет"
            description="Проект — это одна схема: её источники, вопросы и версии."
            action={
              <Button variant="primary" leadingIcon="plus">
                Новый проект
              </Button>
            }
          />
          <EmptyState
            size="sm"
            backdrop="dots"
            icon="circle-check"
            title="Открытых вопросов нет"
            action={
              <Button size="sm" leadingIcon="diagram">
                Построить схему
              </Button>
            }
          />
        </div>
      </Specimen>
    </Section>
  )
}

export function LayoutSection() {
  return (
    <Section
      id="layout"
      eyebrow="17 Компоненты"
      title="Карточки и области"
      lead="Card группирует связанное содержимое; карточки не вкладываем друг в друга. ScrollArea — единственный способ прокрутки в экранах. Divider ставим, только когда отступа не хватает."
    >
      <SpecimenGrid>
        <Specimen title="Card" note="outline, elevated, sunken, interactive" canvas>
          <div className="grid grid-cols-2 gap-4">
            <Card>
              <CardHeader title="outline" description="По умолчанию" />
            </Card>
            <Card variant="elevated">
              <CardHeader title="elevated" description="Над фоном" />
            </Card>
            <Card variant="sunken">
              <CardHeader title="sunken" description="Цитата, пример" />
            </Card>
            <Card interactive tabIndex={0} role="button" aria-label="Открыть вопрос">
              <CardHeader
                title="interactive"
                description="Наведите и сфокусируйте"
                actions={<IconButton size="sm" icon="dots" label="Ещё" />}
              />
            </Card>
          </div>
        </Specimen>
        <Specimen title="ScrollArea" note="скроллбар проявляется при наведении">
          <ScrollArea className="h-56 rounded-md border border-border">
            <ul className="divide-y divide-border">
              {QUESTION_NUMBERS.map((n) => (
                <li key={n} className="flex items-center justify-between gap-3 px-3 py-2.5">
                  <span className="type-ui truncate text-fg">
                    Вопрос {n}: кто выполняет проверку комплектности заявки
                  </span>
                  <Badge tone={n % 3 === 1 ? 'amber' : 'neutral'}>
                    {n % 3 === 1 ? 'Допущение' : 'Открыт'}
                  </Badge>
                </li>
              ))}
            </ul>
          </ScrollArea>
          <Caption>Виртуальные списки: передайте viewportRef в @tanstack/react-virtual.</Caption>
        </Specimen>
      </SpecimenGrid>
    </Section>
  )
}
