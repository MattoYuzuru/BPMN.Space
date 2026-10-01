import { useState } from 'react'
import { cn } from '@/shared/lib/cn'
import { Badge, Button, Icon, iconNames, Tooltip } from '@/shared/ui'
import {
  Caption,
  PaletteChip,
  ratio,
  Section,
  Specimen,
  SpecimenGrid,
  type TokenValue,
  useTokenValues,
} from './kit'

/* ------------------------------- Принципы ------------------------------- */

const PRINCIPLES = [
  {
    icon: 'bolt',
    title: 'Тишина по умолчанию',
    text: 'Нейтральный Графит и Иней несут интерфейс. Цвет появляется, только когда он что-то значит: Ток — действие, Янтарь — допущение, Хвоя — решено.',
  },
  {
    icon: 'typography',
    title: 'Точность вместо украшений',
    text: 'Тонкие линии, плотная типографика 13px, ровная сетка 4px. Иерархию строят размер, вес и отступ, а не рамки и тени.',
  },
  {
    icon: 'components',
    title: 'Один способ',
    text: 'Каждая задача решается одним компонентом. Не больше трёх уровней важности. Новый экран собирается из готового.',
  },
  {
    icon: 'route',
    title: 'Честное состояние',
    text: 'Скелетон вместо спиннера, линия тока вместо «подождите», янтарный пунктир для всего, что система предположила сама.',
  },
] as const

export function PrinciplesSection() {
  return (
    <Section
      id="principles"
      eyebrow="01 Основы"
      title="Принципы"
      lead="Спокойный инструмент для аналитика: ничего лишнего на экране, всё важное — на своём месте."
    >
      <div className="@container">
        <div className="grid gap-px overflow-hidden rounded-xl border border-border bg-border @3xl:grid-cols-2 @6xl:grid-cols-4">
          {PRINCIPLES.map((principle) => (
            <div key={principle.title} className="flex flex-col gap-3 bg-surface p-6">
              <span className="grid size-8 place-items-center rounded-md border border-border bg-bg-subtle text-accent-fg">
                <Icon name={principle.icon} />
              </span>
              <h3 className="type-subheading text-fg">{principle.title}</h3>
              <p className="type-ui text-fg-muted">{principle.text}</p>
            </div>
          ))}
        </div>
      </div>
    </Section>
  )
}

/* -------------------------------- Палитра -------------------------------- */

interface Family {
  id: string
  name: string
  role: string
  steps: number[]
  key: number
  service?: boolean
}

const FAMILIES: Family[] = [
  {
    id: 'frost',
    name: 'Иней',
    role: 'Светлая нейтральная база. Фон и поверхности светлой темы, текст тёмной.',
    steps: [0, 50, 100, 150, 200, 300],
    key: 50,
  },
  {
    id: 'graphite',
    name: 'Графит',
    role: 'Тёмная нейтральная база. Текст светлой темы, поверхности тёмной.',
    steps: [300, 400, 500, 600, 700, 750, 800, 850, 900, 925, 950],
    key: 850,
  },
  {
    id: 'tok',
    name: 'Ток',
    role: 'Акцент: главное действие, выбор, фокус, ход процесса. Мотив фирменного синего Интер РАО.',
    steps: [50, 100, 200, 300, 400, 500, 600, 650, 700, 800, 900, 950],
    key: 600,
  },
  {
    id: 'amber',
    name: 'Янтарь',
    role: 'Допущения и внимание. Между оранжевым Интер РАО и жёлтым Яндекса.',
    steps: [50, 100, 200, 300, 400, 500, 600, 700, 800, 900, 950],
    key: 500,
  },
  {
    id: 'pine',
    name: 'Хвоя',
    role: 'Решено, успех, добавлено. Глубокий хвойный зелёный.',
    steps: [50, 100, 200, 300, 400, 500, 600, 700, 800, 900, 950],
    key: 600,
  },
  {
    id: 'surik',
    name: 'Сурик',
    role: 'Служебный. Только ошибки и необратимые действия, никогда — для украшения.',
    steps: [50, 100, 200, 300, 400, 500, 600, 700, 800, 900, 950],
    key: 600,
    service: true,
  },
]

const PALETTE_VARS = FAMILIES.flatMap((family) =>
  family.steps.map((step) => `--palette-${family.id}-${step}`),
)

export function PaletteSection() {
  const values = useTokenValues(PALETTE_VARS)
  return (
    <Section
      id="palette"
      eyebrow="02 Основы"
      title="Палитра"
      lead="Пять основных цветов и служебный Сурик. Шкалы построены в OKLCH: ступени одной светлоты у разных цветов воспринимаются одинаково яркими, поэтому цвета не спорят."
    >
      <div className="flex flex-col gap-3">
        {FAMILIES.map((family) => {
          const keyVar = `--palette-${family.id}-${family.key}`
          return (
            <div
              key={family.id}
              className="grid gap-5 rounded-xl border border-border bg-surface p-5 @3xl:grid-cols-[14rem_1fr]"
            >
              <div className="flex gap-4 @3xl:flex-col @3xl:gap-3">
                <PaletteChip cssVar={keyVar} className="h-14 w-20 shrink-0 @3xl:h-16 @3xl:w-full" />
                <div className="flex flex-col gap-1">
                  <div className="flex items-center gap-2">
                    <h3 className="type-heading text-fg">{family.name}</h3>
                    {family.service && <Badge tone="danger">служебный</Badge>}
                  </div>
                  <p className="type-caption text-fg-muted">{family.role}</p>
                  <span className="type-code text-fg-subtle">{values[keyVar]?.hex}</span>
                </div>
              </div>
              <div className="grid grid-flow-col gap-1.5 auto-cols-fr">
                {family.steps.map((step) => {
                  const name = `--palette-${family.id}-${step}`
                  return (
                    <Tooltip key={step} content={values[name]?.raw}>
                      <div className="flex min-w-0 flex-col gap-1.5 rounded-md outline-offset-2">
                        <PaletteChip
                          cssVar={name}
                          className={cn('h-10', step === family.key && 'ring-2 ring-fg/20')}
                        />
                        <span className="type-code truncate text-fg">{step}</span>
                        <span className="-mt-1.5 truncate font-mono text-2xs text-fg-subtle">
                          {values[name]?.hex}
                        </span>
                      </div>
                    </Tooltip>
                  )
                })}
              </div>
            </div>
          )
        })}
      </div>
    </Section>
  )
}

/* --------------------------- Семантические токены --------------------------- */

interface TokenRow {
  name: string
  /** Литеральный класс заливки — Tailwind видит его в исходнике. */
  swatch: string
  use: string
  /** Проверять контраст: text — 4.5 к surface, ui — 3 к surface, onAccent — к accent. */
  check?: 'text' | 'ui' | 'onAccent'
  textClass?: string
}

const TOKEN_GROUPS: { title: string; rows: TokenRow[] }[] = [
  {
    title: 'Поверхности',
    rows: [
      { name: 'bg', swatch: 'bg-bg', use: 'Фон приложения' },
      { name: 'bg-subtle', swatch: 'bg-bg-subtle', use: 'Боковые панели, утопленные блоки' },
      { name: 'surface', swatch: 'bg-surface', use: 'Панели, карточки, поля' },
      { name: 'surface-raised', swatch: 'bg-surface-raised', use: 'Меню, поповеры, тосты' },
      { name: 'surface-hover', swatch: 'bg-surface-hover', use: 'Наведение на secondary' },
      { name: 'hover', swatch: 'bg-hover', use: 'Наведение на прозрачное' },
      { name: 'pressed', swatch: 'bg-pressed', use: 'Нажатие, открытое меню' },
      { name: 'overlay', swatch: 'bg-overlay', use: 'Затемнение под диалогом' },
    ],
  },
  {
    title: 'Линии и фокус',
    rows: [
      { name: 'border', swatch: 'bg-border', use: 'Разделители, рамки' },
      { name: 'border-strong', swatch: 'bg-border-strong', use: 'Рамка при наведении' },
      { name: 'control', swatch: 'bg-control', use: 'Рамка чекбокса и радио', check: 'ui' },
      { name: 'focus-ring', swatch: 'bg-focus-ring', use: 'Кольцо фокуса', check: 'ui' },
    ],
  },
  {
    title: 'Текст',
    rows: [
      { name: 'fg', swatch: 'bg-fg', use: 'Основной текст', check: 'text', textClass: 'text-fg' },
      {
        name: 'fg-muted',
        swatch: 'bg-fg-muted',
        use: 'Вторичный текст, описания',
        check: 'text',
        textClass: 'text-fg-muted',
      },
      {
        name: 'fg-subtle',
        swatch: 'bg-fg-subtle',
        use: 'Метаданные, плейсхолдеры',
        check: 'text',
        textClass: 'text-fg-subtle',
      },
      {
        name: 'fg-on-accent',
        swatch: 'bg-fg-on-accent',
        use: 'Текст на заливке Тока и Сурика',
        check: 'onAccent',
      },
    ],
  },
  {
    title: 'Ток',
    rows: [
      { name: 'accent', swatch: 'bg-accent', use: 'Primary-кнопка, выбор, ток', check: 'ui' },
      { name: 'accent-hover', swatch: 'bg-accent-hover', use: 'Наведение на primary' },
      { name: 'accent-subtle', swatch: 'bg-accent-subtle', use: 'Фон выбранного' },
      {
        name: 'accent-fg',
        swatch: 'bg-accent-fg',
        use: 'Текст и иконки акцентом',
        check: 'text',
        textClass: 'text-accent-fg',
      },
    ],
  },
  {
    title: 'Янтарь',
    rows: [
      { name: 'amber', swatch: 'bg-amber', use: 'Пунктир допущения, иконка', check: 'ui' },
      { name: 'amber-subtle', swatch: 'bg-amber-subtle', use: 'Фон допущения' },
      {
        name: 'amber-fg',
        swatch: 'bg-amber-fg',
        use: 'Текст допущения',
        check: 'text',
        textClass: 'text-amber-fg',
      },
    ],
  },
  {
    title: 'Хвоя',
    rows: [
      { name: 'success', swatch: 'bg-success', use: 'Иконка «решено»', check: 'ui' },
      { name: 'success-subtle', swatch: 'bg-success-subtle', use: 'Фон «решено»' },
      {
        name: 'success-fg',
        swatch: 'bg-success-fg',
        use: 'Текст «решено»',
        check: 'text',
        textClass: 'text-success-fg',
      },
    ],
  },
  {
    title: 'Сурик',
    rows: [
      { name: 'danger', swatch: 'bg-danger', use: 'Ошибка, удаление', check: 'ui' },
      { name: 'danger-subtle', swatch: 'bg-danger-subtle', use: 'Фон ошибки' },
      {
        name: 'danger-fg',
        swatch: 'bg-danger-fg',
        use: 'Текст ошибки',
        check: 'text',
        textClass: 'text-danger-fg',
      },
    ],
  },
]

const TOKEN_VARS = TOKEN_GROUPS.flatMap((group) => group.rows.map((row) => `--color-${row.name}`))

function ContrastMark({ value, min }: { value: number | null; min: number }) {
  if (value === null) return null
  const ok = value >= min
  return (
    <Tooltip content={ok ? `Проходит AA (нужно ${min}:1)` : `Ниже AA (нужно ${min}:1)`}>
      <span
        data-numeric
        className={cn(
          'inline-flex items-center gap-1 rounded-xs px-1 font-mono text-2xs',
          ok ? 'text-success-fg' : 'text-danger-fg',
        )}
      >
        <Icon name={ok ? 'check' : 'alert-triangle'} size={14} />
        {value.toFixed(1)}
      </span>
    </Tooltip>
  )
}

function TokenCell({
  theme,
  row,
  values,
}: {
  theme: 'light' | 'dark'
  row: TokenRow
  values: Record<string, TokenValue>
}) {
  const own = values[`--color-${row.name}`]
  const surface = values['--color-surface']
  const accent = values['--color-accent']
  const value =
    row.check === 'onAccent' ? ratio(own, accent) : row.check ? ratio(own, surface) : null
  return (
    <div
      data-theme={theme}
      className="flex items-center gap-2.5 rounded-md border border-border bg-surface px-2 py-1.5"
    >
      <span
        className={cn('size-6 shrink-0 rounded-sm ring-1 ring-border ring-inset', row.swatch)}
      />
      {row.textClass ? (
        <span className={cn('type-subheading', row.textClass)}>Аа</span>
      ) : row.check === 'onAccent' ? (
        <span className="rounded-xs bg-accent px-1 type-subheading text-fg-on-accent">Аа</span>
      ) : null}
      <span className="type-code min-w-0 flex-1 truncate text-fg-muted">{own?.hex}</span>
      <ContrastMark value={value} min={row.check === 'ui' ? 3 : 4.5} />
    </div>
  )
}

export function TokensSection() {
  const light = useTokenValues(TOKEN_VARS, 'light')
  const dark = useTokenValues(TOKEN_VARS, 'dark')
  return (
    <Section
      id="tokens"
      eyebrow="03 Основы"
      title="Семантические цвета"
      lead="Экраны используют только эти имена: bg-surface, text-fg-muted, border-border. Значения меняются вместе с темой. Числа справа — контраст WCAG к surface; тест проверяет их при каждом прогоне."
    >
      <div className="overflow-hidden rounded-xl border border-border bg-surface">
        <div className="grid grid-cols-[minmax(12rem,1.1fr)_1fr_1fr] gap-4 border-b border-border bg-bg-subtle px-5 py-2.5 type-label text-fg-muted">
          <span>Токен</span>
          <span>Светлая</span>
          <span>Тёмная</span>
        </div>
        {TOKEN_GROUPS.map((group) => (
          <div key={group.title} className="border-b border-border last:border-b-0">
            <div className="px-5 pt-4 pb-1 type-caption text-fg-subtle">{group.title}</div>
            {group.rows.map((row) => (
              <div
                key={row.name}
                className="grid grid-cols-[minmax(12rem,1.1fr)_1fr_1fr] items-center gap-4 px-5 py-1.5"
              >
                <div className="flex min-w-0 flex-col">
                  <span className="type-code text-fg">{row.name}</span>
                  <span className="type-caption truncate text-fg-muted">{row.use}</span>
                </div>
                <TokenCell theme="light" row={row} values={light} />
                <TokenCell theme="dark" row={row} values={dark} />
              </div>
            ))}
          </div>
        ))}
      </div>
    </Section>
  )
}

/* ------------------------------ Типографика ------------------------------ */

const TYPE_ROLES = [
  ['type-display', 'Display', 'Пустой экран первого запуска', '28–40 / 1.12 / 600'],
  ['type-title', 'Title', 'Заголовок страницы, название проекта', '22–28 / 1.25 / 600'],
  ['type-heading', 'Heading', 'Раздел, диалог, панель', '16–18 / 1.45 / 600'],
  ['type-subheading', 'Subheading', 'Карточка, группа', '13 / 20 / 600'],
  ['type-body', 'Body', 'Текст источников, вопросов, цитат', '14 / 22 / 400'],
  ['type-ui', 'UI', 'Основной текст интерфейса', '13 / 20 / 400'],
  ['type-label', 'Label', 'Подписи полей, заголовки колонок', '12 / 16 / 500'],
  ['type-caption', 'Caption', 'Время, автор, счётчики', '12 / 16 / 400'],
  ['type-code', 'Code', 'Идентификаторы, XML, клавиши', '12 / 16 / mono'],
] as const

export function TypographySection() {
  return (
    <Section
      id="typography"
      eyebrow="04 Основы"
      title="Типографика"
      lead="Geist и Geist Mono, локальные файлы с кириллицей. Девять ролей вместо произвольных размеров: класс type-* задаёт кегль, интерлиньяж, вес и трекинг сразу. Заголовки растут с шириной окна."
    >
      <SpecimenGrid>
        <Specimen title="Geist" note="Sans, 100–900, вариативный">
          <div className="flex flex-col gap-4">
            <span className="type-display text-fg">Аа Бб Вв Ёё</span>
            <p className="type-body text-fg-muted">
              Заявитель подаёт заявку в сетевую организацию. Если мощность до 150 кВт, договор
              направляется в течение 10 дней.
            </p>
            <span className="type-code text-fg-subtle">
              АБВГДЕЁЖЗИЙКЛМНОПРСТУФХЦЧШЩЪЫЬЭЮЯ abcdefghijklmnopqrstuvwxyz
            </span>
          </div>
        </Specimen>
        <Specimen title="Числа" note="tabular-nums: таблицы, счётчики, время">
          <div className="grid grid-cols-2 gap-6">
            <div className="flex flex-col gap-1">
              <Caption>Пропорциональные</Caption>
              <span className="type-heading text-fg">1 111 111</span>
              <span className="type-heading text-fg">8 808 080</span>
            </div>
            <div className="flex flex-col gap-1" data-numeric>
              <Caption>Табличные</Caption>
              <span className="type-heading text-fg">1 111 111</span>
              <span className="type-heading text-fg">8 808 080</span>
            </div>
          </div>
          <p className="type-code mt-5 text-fg-muted">
            Geist Mono: gpt://b1g/qwen3.6-35b-a3b/latest 0O1lI
          </p>
        </Specimen>
      </SpecimenGrid>
      <div className="overflow-hidden rounded-xl border border-border bg-surface">
        {TYPE_ROLES.map(([className, name, use, metrics]) => (
          <div
            key={className}
            className="grid items-baseline gap-x-6 gap-y-1 border-b border-border px-5 py-4 last:border-b-0 @3xl:grid-cols-[10rem_1fr_12rem]"
          >
            <div className="flex flex-col">
              <span className="type-code text-fg">{className}</span>
              <span className="type-caption text-fg-subtle">{name}</span>
            </div>
            <span className={cn(className, 'truncate text-fg')}>{use}</span>
            <span className="type-code text-fg-subtle @3xl:text-right" data-numeric>
              {metrics}
            </span>
          </div>
        ))}
      </div>
    </Section>
  )
}

/* --------------------------- Сетка и отступы --------------------------- */

const SPACING = [
  ['1', 'w-1', 'Иконка и текст в бейдже'],
  ['2', 'w-2', 'Иконка и подпись в кнопке'],
  ['3', 'w-3', 'Элементы в строке, поля в форме'],
  ['4', 'w-4', 'Внутренний отступ карточки'],
  ['5', 'w-5', 'Внутренний отступ диалога и панели'],
  ['6', 'w-6', 'Между карточками'],
  ['8', 'w-8', 'Между группами'],
  ['12', 'w-12', 'Между разделами страницы'],
  ['16', 'w-16', 'Вокруг пустого состояния'],
] as const

export function SpacingSection() {
  return (
    <Section
      id="spacing"
      eyebrow="05 Основы"
      title="Сетка и отступы"
      lead="Шаг 4px. Плотность — как у рабочих инструментов: строка 32px, кнопка 32px, текст 13px. Окно от 1024 до 2560px: панели растягиваются, длинный текст держит ширину строки до 72 знаков."
    >
      <SpecimenGrid>
        <Specimen title="Шкала отступов" note="Tailwind: p-4, gap-3, mt-6">
          <div className="flex flex-col gap-2.5">
            {SPACING.map(([step, width, use]) => (
              <div key={step} className="grid grid-cols-[2.5rem_4.5rem_1fr] items-center gap-3">
                <span className="type-code text-fg" data-numeric>
                  {step}
                </span>
                <span className={cn('h-2 rounded-xs bg-accent/70', width)} />
                <span className="type-caption text-fg-muted">
                  {Number(step) * 4} px, {use.toLowerCase()}
                </span>
              </div>
            ))}
          </div>
        </Specimen>
        <Specimen title="Ширина окна" note="только десктоп, без мобильной вёрстки">
          <div className="flex flex-col gap-4">
            {[
              ['База', 'от 1024px', 'Три панели, боковые сворачиваются'],
              ['wide:', 'от 1440px', 'Панели шире, больше колонок в списках'],
              ['ultra:', 'от 1920px', 'Ограничиваем ширину текста, растёт холст'],
            ].map(([prefix, from, text]) => (
              <div key={prefix} className="flex items-start gap-3">
                <Badge tone="accent" variant="outline">
                  {prefix}
                </Badge>
                <div className="flex flex-col">
                  <span className="type-subheading text-fg">{from}</span>
                  <span className="type-caption text-fg-muted">{text}</span>
                </div>
              </div>
            ))}
            <p className="type-caption text-fg-muted">
              Внутри панелей — контейнерные запросы (@container, @3xl:): компонент подстраивается
              под ширину своей панели, а не окна.
            </p>
          </div>
        </Specimen>
      </SpecimenGrid>
    </Section>
  )
}

/* ------------------------- Радиусы и поверхности ------------------------- */

const RADII = [
  ['xs', 'rounded-xs', '4px', 'Чекбокс, клавиша, пункт меню'],
  ['sm', 'rounded-sm', '6px', 'Малая кнопка, бейдж, подсказка'],
  ['md', 'rounded-md', '8px', 'Кнопка, поле, меню'],
  ['lg', 'rounded-lg', '12px', 'Карточка, поповер, диалог'],
  ['xl', 'rounded-xl', '16px', 'Крупные блоки'],
] as const

const SHADOWS = [
  ['shadow-xs', 'Кнопки и поля'],
  ['shadow-sm', 'Карточка над фоном'],
  ['shadow-md', 'Меню, поповер, подсказка'],
  ['shadow-lg', 'Диалог, панель, тост'],
  ['shadow-glow', 'Свечение тока: одна активная вещь'],
] as const

export function SurfacesSection() {
  return (
    <Section
      id="surfaces"
      eyebrow="06 Основы"
      title="Радиусы и поверхности"
      lead="Чем выше слой, тем светлее поверхность и мягче тень. В тёмной теме тени глубже, а верхняя кромка слоя едва светится."
    >
      <Specimen title="Радиусы" note="вложенный радиус = внешний минус отступ">
        <div className="grid grid-cols-5 gap-4">
          {RADII.map(([name, className, px, use]) => (
            <div key={name} className="flex flex-col gap-2">
              <div className={cn('h-16 border border-border-strong bg-bg-subtle', className)} />
              <span className="type-code text-fg">
                {name} {px}
              </span>
              <span className="type-caption text-fg-muted">{use}</span>
            </div>
          ))}
        </div>
      </Specimen>
      <Specimen title="Уровни и тени" canvas>
        <div className="grid grid-cols-5 gap-5">
          {SHADOWS.map(([className, use]) => (
            <div key={className} className="flex flex-col gap-3">
              <div
                className={cn(
                  'h-20 rounded-lg border bg-surface-raised',
                  className === 'shadow-glow' ? 'border-accent/45' : 'border-border',
                  className,
                )}
              />
              <span className="type-code text-fg">{className}</span>
              <span className="type-caption text-fg-muted">{use}</span>
            </div>
          ))}
        </div>
      </Specimen>
      <Specimen title="Слои" note="bg-subtle, bg, surface, surface-raised">
        <div className="rounded-lg border border-border bg-bg-subtle p-4">
          <span className="type-caption text-fg-subtle">bg-subtle: боковая панель</span>
          <div className="mt-3 rounded-lg border border-border bg-bg p-4">
            <span className="type-caption text-fg-subtle">bg: фон рабочей области</span>
            <div className="mt-3 max-w-xl rounded-lg border border-border bg-surface p-4 shadow-sm">
              <span className="type-caption text-fg-subtle">surface: карточка</span>
              <div className="mt-3 w-64 rounded-md border border-border bg-surface-raised p-3 shadow-md">
                <span className="type-caption text-fg-subtle">surface-raised: меню</span>
              </div>
            </div>
          </div>
        </div>
      </Specimen>
    </Section>
  )
}

/* -------------------------------- Движение -------------------------------- */

const DURATIONS = [
  ['duration-fast', '120 мс', 'Подсветка пункта меню, исчезновение', 'duration-fast'],
  ['duration-base', '200 мс', 'Наведение, появление поповера', 'duration-base'],
  ['duration-slow', '320 мс', 'Диалог, панель, бегунок, смена темы', 'duration-slow'],
] as const

export function MotionSection() {
  const [moved, setMoved] = useState(false)
  return (
    <Section
      id="motion"
      eyebrow="07 Основы"
      title="Движение"
      lead="Движение объясняет, откуда пришёл слой и куда ушёл, — и ничего больше. Вход мягко замедляется (ease-soft), выход короче входа. При «уменьшении движения» в системе всё мгновенно, циклы останавливаются."
    >
      <SpecimenGrid>
        <Specimen title="Длительности" note="ease-soft: cubic-bezier(0.22, 1, 0.36, 1)">
          <div className="flex flex-col gap-4">
            {DURATIONS.map(([name, ms, use, duration]) => (
              <div key={name} className="flex flex-col gap-1.5">
                <div className="flex items-baseline justify-between gap-3">
                  <span className="type-code text-fg">{name}</span>
                  <span className="type-caption text-fg-subtle" data-numeric>
                    {ms}
                  </span>
                </div>
                <div className="relative h-7 rounded-md bg-bg-subtle">
                  <span
                    className={cn(
                      'absolute top-1 left-1 size-5 rounded-sm bg-accent shadow-xs transition-transform ease-soft',
                      duration,
                      moved && 'translate-x-56',
                    )}
                  />
                </div>
                <span className="type-caption text-fg-muted">{use}</span>
              </div>
            ))}
            <div>
              <Button
                size="sm"
                leadingIcon="player-play"
                onClick={() => setMoved((value) => !value)}
              >
                Воспроизвести
              </Button>
            </div>
          </div>
        </Specimen>
        <Specimen title="Что анимируем" note="и чего не анимируем">
          <ul className="flex flex-col gap-3">
            {[
              ['check', 'Цвет, фон, рамку при наведении — всегда, base'],
              ['check', 'Появление слоёв: прозрачность, сдвиг 4–8px, масштаб 0.97'],
              ['check', 'Бегунок вкладок и сегментов, прорисовка галочки'],
              ['check', 'Ход процесса: линия тока, дыхание текущего этапа'],
              ['x', 'Размер и положение раскладки, высоту списков'],
              ['x', 'Пружины, отскоки, вращения, параллакс'],
              ['x', 'Бесконечные анимации вне хода процесса и скелетонов'],
            ].map(([icon, text]) => (
              <li key={text} className="flex items-start gap-2.5">
                <Icon
                  name={icon === 'check' ? 'check' : 'x'}
                  className={icon === 'check' ? 'text-success' : 'text-fg-subtle'}
                />
                <span className="type-ui text-fg">{text}</span>
              </li>
            ))}
          </ul>
        </Specimen>
      </SpecimenGrid>
    </Section>
  )
}

/* -------------------------------- Иконки -------------------------------- */

export function IconsSection() {
  return (
    <Section
      id="icons"
      eyebrow="08 Основы"
      title="Иконки"
      lead={`Tabler Icons, обводка 1.5, размеры 14, 16, 20 и 24. Только через <Icon name="…" />: реестр — src/shared/ui/icon/registry.ts, сейчас ${iconNames.length} имён.`}
    >
      <Specimen title="Размеры">
        <div className="flex items-end gap-8">
          {([14, 16, 20, 24] as const).map((size) => (
            <div key={size} className="flex flex-col items-center gap-2 text-fg">
              <Icon name="diagram" size={size} />
              <span className="type-code text-fg-subtle">{size}</span>
            </div>
          ))}
          <p className="type-caption ml-4 max-w-md text-fg-muted">
            14 — в плотных строках и бейджах, 16 — по умолчанию в кнопках и меню, 20 — в пустых
            состояниях и крупных кнопках, 24 — редко, для иллюстративных мест.
          </p>
        </div>
      </Specimen>
      <div className="grid grid-cols-[repeat(auto-fill,minmax(8.5rem,1fr))] gap-px overflow-hidden rounded-xl border border-border bg-border">
        {iconNames.map((name) => (
          <div
            key={name}
            className="flex flex-col items-center gap-2.5 bg-surface px-2 py-4 text-fg-muted transition-colors duration-base hover:bg-surface-hover hover:text-fg"
          >
            <Icon name={name} size={20} />
            <span className="type-code max-w-full truncate text-fg-subtle">{name}</span>
          </div>
        ))}
      </div>
    </Section>
  )
}
