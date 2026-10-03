import { useEffect, useState } from 'react'
import {
  AudioLevel,
  BrandMark,
  Button,
  Checkbox,
  Field,
  FileDrop,
  IconButton,
  Input,
  Kbd,
  RadioGroup,
  RadioGroupItem,
  SegmentedControl,
  Select,
  Switch,
  Textarea,
} from '@/shared/ui'
import { Caption, Section, Specimen, SpecimenGrid } from './kit'

const VARIANTS = ['primary', 'secondary', 'ghost'] as const

export function ButtonsSection() {
  const [loading, setLoading] = useState(false)
  const run = () => {
    setLoading(true)
    window.setTimeout(() => setLoading(false), 1600)
  }
  return (
    <Section
      id="buttons"
      eyebrow="10 Компоненты"
      title="Кнопки"
      lead="Три уровня важности. Primary — одно главное действие экрана. Secondary — обычные действия. Ghost — тулбары и строки списков. Тон danger — только необратимое. Подпись — глагол: «Построить схему», а не «Ок»."
    >
      <Specimen title="Button" note="variant, tone, size">
        <div className="flex flex-col gap-6">
          {VARIANTS.map((variant) => (
            <div key={variant} className="grid grid-cols-[6rem_1fr] items-center gap-4">
              <span className="type-code text-fg-subtle">{variant}</span>
              <div className="flex flex-wrap items-center gap-3">
                <Button variant={variant} size="sm">
                  Ответить
                </Button>
                <Button variant={variant}>Построить схему</Button>
                <Button variant={variant} size="lg" leadingIcon="plus">
                  Новый проект
                </Button>
                <Button variant={variant} trailingIcon="chevron-down">
                  Скачать
                </Button>
                <Button variant={variant} tone="danger" leadingIcon="trash">
                  Удалить
                </Button>
                <Button variant={variant} disabled>
                  Недоступно
                </Button>
              </div>
            </div>
          ))}
          <div className="grid grid-cols-[6rem_1fr] items-center gap-4">
            <span className="type-code text-fg-subtle">loading</span>
            <div className="flex items-center gap-3">
              <Button variant="primary" loading={loading} onClick={run} leadingIcon="diagram">
                Построить схему
              </Button>
              <Button loading={loading} onClick={run}>
                Сохранить версию
              </Button>
              <span className="type-caption text-fg-muted">
                Нажмите: ширина не меняется, кнопка недоступна до конца действия.
              </span>
            </div>
          </div>
        </div>
      </Specimen>
      <SpecimenGrid>
        <Specimen title="IconButton" note="подпись обязательна, показывается в подсказке">
          <div className="flex flex-col gap-4">
            {VARIANTS.map((variant) => (
              <div key={variant} className="flex items-center gap-2">
                <span className="type-code w-24 text-fg-subtle">{variant}</span>
                <IconButton variant={variant} size="sm" icon="plus" label="Добавить источник" />
                <IconButton variant={variant} icon="microphone" label="Записать голос" />
                <IconButton variant={variant} size="lg" icon="send" label="Отправить ответ" />
                <IconButton variant={variant} icon="trash" tone="danger" label="Удалить источник" />
                <IconButton
                  variant={variant}
                  icon="layout-sidebar"
                  label="Свернуть панель"
                  shortcut={['mod', 'b']}
                />
              </div>
            ))}
          </div>
        </Specimen>
        <Specimen title="Kbd" note="mod — ⌘ на macOS и Ctrl на остальных">
          <div className="flex flex-col gap-3">
            {[
              [['mod', 'k'], 'Палитра команд'],
              [['mod', 'enter'], 'Отправить ответ'],
              [['shift', 'mod', 'z'], 'Повторить'],
              [['esc'], 'Закрыть'],
            ].map(([keys, label]) => (
              <div key={String(label)} className="flex items-center justify-between gap-4">
                <span className="type-ui text-fg">{label}</span>
                <Kbd keys={keys as string[]} />
              </div>
            ))}
          </div>
        </Specimen>
      </SpecimenGrid>
    </Section>
  )
}

export function FieldsSection() {
  const [answer, setAnswer] = useState(
    'Бюджет согласуют в финансовом отделе, это есть в документе «Финансы проекта».',
  )
  const [dropped, setDropped] = useState<string[]>([])
  const levels = useDemoLevels()
  return (
    <Section
      id="fields"
      eyebrow="11 Компоненты"
      title="Поля ввода"
      lead="Field связывает подпись, подсказку и ошибку с полем. Подсказку пишем, только если без неё поле нельзя заполнить. Обязательные поля не помечаем звёздочкой — помечаем необязательные. Файлы принимает FileDrop, голос показывает AudioLevel."
    >
      <SpecimenGrid>
        <Specimen title="Input" note="Field + Input">
          <div className="flex flex-col gap-5">
            <Field label="Название проекта">
              <Input placeholder="Например, Техприсоединение" />
            </Field>
            <Field label="Поиск" optional>
              <Input
                leadingIcon="search"
                placeholder="Найти в источниках"
                trailing={<Kbd keys={['mod', 'f']} />}
              />
            </Field>
            <Field label="Ссылка на регламент" error="Ссылка должна начинаться с https://">
              <Input leadingIcon="link" defaultValue="consultant.ru/document" />
            </Field>
            <div className="grid grid-cols-2 gap-3">
              <Field label="Малое поле">
                <Input size="sm" placeholder="sm, 28px" />
              </Field>
              <Field label="Недоступно" disabled>
                <Input defaultValue="Только чтение" />
              </Field>
            </div>
          </div>
        </Specimen>
        <Specimen title="Textarea" note="растёт по тексту от minRows до maxRows">
          <div className="flex flex-col gap-5">
            <Field label="Ответ на вопрос" aside={<span data-numeric>{answer.length} / 2000</span>}>
              <Textarea
                minRows={3}
                maxRows={8}
                value={answer}
                onChange={(event) => setAnswer(event.target.value)}
              />
            </Field>
            <Field label="Заметка со встречи" hint="Текст станет источником проекта.">
              <Textarea minRows={2} placeholder="Вставьте или наберите текст" />
            </Field>
          </div>
        </Specimen>
        <Specimen title="FileDrop" note="перетаскивание и кнопка выбора">
          <FileDrop
            accept=".txt,.md,.csv,.docx,.pdf"
            multiple
            onFiles={(files) => setDropped(files.map((file) => file.name))}
            title="Перетащите документ"
            hint=".txt, .md, .csv, .docx, .pdf"
          />
          {dropped.length > 0 && <Caption>Получено: {dropped.join(', ')}</Caption>}
        </Specimen>
        <Specimen title="AudioLevel" note="уровень сигнала при записи голоса">
          <div className="flex flex-col gap-4">
            <AudioLevel levels={levels} label="Уровень сигнала, пример" />
            <AudioLevel levels={levels} active={false} bars={32} className="h-8" label="Пауза" />
            <div className="flex items-center gap-3">
              <BrandMark size="sm" />
              <BrandMark />
              <BrandMark size="lg" />
              <Caption>BrandMark — знак продукта: шапка, 404, пустые экраны.</Caption>
            </div>
          </div>
        </Specimen>
      </SpecimenGrid>
    </Section>
  )
}

/** Псевдоречь для витрины уровня сигнала: слоги с паузами, без микрофона. */
function useDemoLevels() {
  const [levels, setLevels] = useState<number[]>([])
  useEffect(() => {
    let tick = 0
    const timer = setInterval(() => {
      tick += 1
      const syllable = Math.abs(Math.sin(tick / 2.3)) * (tick % 23 < 17 ? 1 : 0.08)
      setLevels((previous) => [...previous.slice(-63), 0.12 + syllable * 0.8])
    }, 90)
    return () => clearInterval(timer)
  }, [])
  return levels
}

const MODELS = [
  { value: 'qwen', label: 'Qwen 3.6 35B', icon: 'bolt' as const },
  { value: 'alice', label: 'Alice AI LLM', icon: 'bolt' as const },
  { value: 'gpt-oss', label: 'GPT-OSS 120B', icon: 'bolt' as const },
  { value: 'local', label: 'Локальная модель', icon: 'lock' as const, disabled: true },
]

export function ChoiceSection() {
  const [model, setModel] = useState('qwen')
  const [view, setView] = useState<'diagram' | 'xml' | 'report'>('diagram')
  const [scale, setScale] = useState<'fit' | '100' | '150'>('fit')
  const [importance, setImportance] = useState('major')
  return (
    <Section
      id="choice"
      eyebrow="12 Компоненты"
      title="Выбор"
      lead="Флажок — независимые пункты. Радио — один из 2–5 видимых вариантов. Select — один из многих. SegmentedControl — режим отображения. Switch — настройка, которая применяется сразу."
    >
      <SpecimenGrid>
        <Specimen title="Checkbox" note="галочка прорисовывается штрихом">
          <div className="flex flex-col gap-3.5">
            <Checkbox label="Учитывать допущения при построении" defaultChecked />
            <Checkbox
              label="Показывать цитаты на схеме"
              description="Элементы схемы получат ссылку на фрагмент источника."
            />
            <Checkbox label="Выбраны не все источники" checked="indeterminate" />
            <Checkbox label="Распознавание голоса" disabled />
            <Checkbox label="Нужно согласие" invalid />
          </div>
        </Specimen>
        <Specimen title="RadioGroup" note="стрелки переключают выбор">
          <RadioGroup value={importance} onValueChange={setImportance} aria-label="Важность">
            <RadioGroupItem value="blocker" label="Блокирует" description="Схему не построить" />
            <RadioGroupItem value="major" label="Важный" />
            <RadioGroupItem value="minor" label="Уточнение" />
            <RadioGroupItem value="off" label="Недоступно" disabled />
          </RadioGroup>
        </Specimen>
        <Specimen title="Switch" note="настройки без кнопки «Сохранить»">
          <div className="flex flex-col gap-3.5">
            <Switch label="Перепроверять после каждого источника" defaultChecked />
            <Switch label="Анимация прохождения токена" />
            <Switch label="Экспорт в PNG" disabled />
          </div>
        </Specimen>
        <Specimen title="Select" note="наш список, а не системный">
          <div className="flex flex-col gap-5">
            <Field label="Модель">
              <Select options={MODELS} value={model} onValueChange={setModel} />
            </Field>
            <div className="grid grid-cols-2 gap-3">
              <Field label="Пустой">
                <Select options={MODELS} placeholder="Выберите модель" />
              </Field>
              <Field label="С ошибкой" error="Выберите модель">
                <Select options={MODELS} size="sm" placeholder="Выберите" />
              </Field>
            </div>
          </div>
        </Specimen>
        <Specimen title="SegmentedControl" note="бегунок мягко переезжает">
          <div className="flex flex-col gap-4">
            <SegmentedControl
              aria-label="Вид"
              value={view}
              onValueChange={setView}
              options={[
                { value: 'diagram', label: 'Схема', icon: 'diagram' },
                { value: 'xml', label: 'XML', icon: 'file-code' },
                { value: 'report', label: 'Отчёт', icon: 'list-check' },
              ]}
            />
            <div className="flex items-center gap-4">
              <SegmentedControl
                aria-label="Масштаб"
                size="sm"
                value={scale}
                onValueChange={setScale}
                options={[
                  { value: 'fit', label: 'По размеру' },
                  { value: '100', label: '100%' },
                  { value: '150', label: '150%' },
                ]}
              />
              <SegmentedControl
                aria-label="Вид"
                size="sm"
                iconOnly
                value={view}
                onValueChange={setView}
                options={[
                  { value: 'diagram', label: 'Схема', icon: 'diagram' },
                  { value: 'xml', label: 'XML', icon: 'file-code' },
                  { value: 'report', label: 'Отчёт', icon: 'list-check' },
                ]}
              />
            </div>
            <Caption>Варианты: 2–4. Больше — уже Select или Tabs.</Caption>
          </div>
        </Specimen>
      </SpecimenGrid>
    </Section>
  )
}
