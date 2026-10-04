import {
  AssumptionFrame,
  Badge,
  Button,
  Card,
  EmptyState,
  Icon,
  IconButton,
  Input,
  ResizableHandle,
  ResizablePanel,
  ResizablePanelGroup,
  ScrollArea,
  SegmentedControl,
  Tag,
} from '@/shared/ui'
import { Section } from './kit'

const SOURCES = [
  { name: 'Регламент ТП.docx', icon: 'file-text', meta: '12 стр.' },
  { name: 'Заметка со встречи', icon: 'microphone', meta: '2:14' },
  { name: 'Финансы проекта.docx', icon: 'file-text', meta: '4 стр.' },
] as const

/** Пример сборки экрана целиком из компонентов дизайн-системы. Без собственных стилей. */
export function ExampleSection() {
  return (
    <Section
      id="example"
      eyebrow="21 Сборка"
      title="Пример экрана"
      lead="Рабочее место аналитика из готовых компонентов: ResizablePanelGroup, ScrollArea, Card, AssumptionFrame, EmptyState на сетке. Тяните разделители."
    >
      <div className="h-[34rem] overflow-hidden rounded-xl border border-border bg-bg shadow-sm">
        <ResizablePanelGroup orientation="horizontal">
          <ResizablePanel defaultSize="24" minSize="200px" className="flex flex-col bg-bg-subtle">
            <div className="flex h-11 items-center justify-between border-b border-border px-3">
              <span className="type-subheading text-fg">Источники</span>
              <IconButton size="sm" icon="plus" label="Добавить источник" />
            </div>
            <ScrollArea className="flex-1">
              <ul className="flex flex-col gap-0.5 p-2">
                {SOURCES.map((source, index) => (
                  <li
                    key={source.name}
                    className={
                      index === 0
                        ? 'flex items-center gap-2.5 rounded-md bg-pressed px-2 py-1.5'
                        : 'flex items-center gap-2.5 rounded-md px-2 py-1.5 transition-colors duration-base hover:bg-hover'
                    }
                  >
                    <Icon name={source.icon} className="text-fg-muted" />
                    <span className="type-ui min-w-0 flex-1 truncate text-fg">{source.name}</span>
                    <span className="type-caption text-fg-subtle" data-numeric>
                      {source.meta}
                    </span>
                  </li>
                ))}
              </ul>
            </ScrollArea>
          </ResizablePanel>
          <ResizableHandle />
          <ResizablePanel minSize="320px" className="flex flex-col">
            <div className="flex h-11 items-center justify-between gap-3 border-b border-border px-3">
              <div className="flex items-center gap-2">
                <span className="type-subheading text-fg">Техприсоединение</span>
                <Badge tone="amber" dot variant="outline">
                  2 допущения
                </Badge>
              </div>
              <SegmentedControl
                aria-label="Вид"
                size="sm"
                iconOnly
                value="diagram"
                onValueChange={() => {}}
                options={[
                  { value: 'diagram', label: 'Схема', icon: 'diagram' },
                  { value: 'xml', label: 'XML', icon: 'file-code' },
                ]}
              />
            </div>
            <div className="relative flex-1">
              <EmptyState
                className="h-full"
                icon="diagram"
                title="Схема появится после прогона"
                action={
                  <Button variant="primary" leadingIcon="bolt">
                    Построить схему
                  </Button>
                }
              />
            </div>
          </ResizablePanel>
          <ResizableHandle />
          <ResizablePanel defaultSize="30" minSize="260px" className="flex flex-col bg-surface">
            <div className="flex h-11 items-center justify-between border-b border-border px-3">
              <span className="type-subheading text-fg">Вопросы</span>
              <div className="flex gap-1.5">
                <Badge tone="success">Решено 2</Badge>
                <Badge tone="accent">Осталось 2</Badge>
              </div>
            </div>
            <ScrollArea className="flex-1">
              <div className="flex flex-col gap-3 p-3">
                <Card glow padding="sm" className="flex flex-col gap-3">
                  <div className="flex items-start justify-between gap-2">
                    <span className="type-subheading text-fg">Кто согласует бюджет?</span>
                    <Badge tone="danger" variant="outline">
                      Блокирует
                    </Badge>
                  </div>
                  <p className="type-caption text-fg-muted">
                    В голосовой заметке: «бюджет согласуется», исполнитель не назван.
                  </p>
                  <AssumptionFrame>Руководитель отдела</AssumptionFrame>
                  <Input
                    size="sm"
                    placeholder="Ответить текстом"
                    trailing={<IconButton size="sm" icon="microphone" label="Ответить голосом" />}
                  />
                  <div className="flex gap-2">
                    <Button size="sm" variant="primary">
                      Ответить
                    </Button>
                    <Button size="sm" variant="ghost">
                      Игнорировать
                    </Button>
                  </div>
                </Card>
                <Card padding="sm" className="flex flex-col gap-2">
                  <span className="type-subheading text-fg">Срок договора: 5 или 10 дней?</span>
                  <p className="type-caption text-fg-muted">Источники противоречат друг другу.</p>
                  <div className="flex flex-wrap gap-1.5">
                    <Tag icon="file-text">Регламент ТП.docx</Tag>
                    <Tag icon="microphone">Заметка со встречи</Tag>
                  </div>
                </Card>
              </div>
            </ScrollArea>
          </ResizablePanel>
        </ResizablePanelGroup>
      </div>
    </Section>
  )
}
