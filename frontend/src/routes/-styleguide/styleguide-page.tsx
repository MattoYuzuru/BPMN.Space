import { useEffect, useState } from 'react'
import { ThemeSwitch } from '@/features/theme-switch/theme-switch'
import { cn } from '@/shared/lib/cn'
import { Badge, Icon, Kbd, ScrollArea } from '@/shared/ui'
import { BrandSection, HeroComposition } from './brand'
import { ButtonsSection, ChoiceSection, FieldsSection } from './controls'
import { FeedbackSection, LayoutSection, NavigationSection, StatusSection } from './display'
import { ExampleSection } from './example'
import {
  IconsSection,
  MotionSection,
  PaletteSection,
  PrinciplesSection,
  SpacingSection,
  SurfacesSection,
  TokensSection,
  TypographySection,
} from './foundations'
import { OverlaysSection } from './overlays'

const NAV = [
  {
    group: 'Основы',
    items: [
      ['principles', 'Принципы'],
      ['palette', 'Палитра'],
      ['tokens', 'Семантические цвета'],
      ['typography', 'Типографика'],
      ['spacing', 'Сетка и отступы'],
      ['surfaces', 'Радиусы и поверхности'],
      ['motion', 'Движение'],
      ['icons', 'Иконки'],
    ],
  },
  { group: 'Приёмы', items: [['brand', 'Фирменные приёмы']] },
  {
    group: 'Компоненты',
    items: [
      ['buttons', 'Кнопки'],
      ['fields', 'Поля ввода'],
      ['choice', 'Выбор'],
      ['overlays', 'Меню и окна'],
      ['navigation', 'Вкладки'],
      ['status', 'Статусы и ход'],
      ['feedback', 'Обратная связь'],
      ['layout', 'Карточки и области'],
    ],
  },
  { group: 'Сборка', items: [['example', 'Пример экрана']] },
] as const

const SECTION_IDS = NAV.flatMap((group) => group.items.map(([id]) => id))

/** Подсвечивает в навигации раздел, который сейчас в верхней части экрана. */
function useActiveSection() {
  const [active, setActive] = useState<string>(SECTION_IDS[0] ?? '')
  useEffect(() => {
    let frame = 0
    // Активен последний раздел, чей верх уже прошёл под шапку (плюс запас в треть экрана).
    const update = () => {
      cancelAnimationFrame(frame)
      frame = requestAnimationFrame(() => {
        const line = 96 + window.innerHeight * 0.25
        let current = SECTION_IDS[0] ?? ''
        for (const id of SECTION_IDS) {
          const top = document.getElementById(id)?.getBoundingClientRect().top
          if (top !== undefined && top <= line) current = id
        }
        setActive(current)
      })
    }
    update()
    window.addEventListener('scroll', update, { passive: true })
    window.addEventListener('resize', update)
    return () => {
      cancelAnimationFrame(frame)
      window.removeEventListener('scroll', update)
      window.removeEventListener('resize', update)
    }
  }, [])
  return active
}

export function StyleguidePage() {
  const active = useActiveSection()
  return (
    <div className="flex min-h-dvh">
      <aside className="sticky top-0 flex h-dvh w-60 shrink-0 flex-col border-r border-border bg-bg-subtle wide:w-64">
        <div className="flex h-14 items-center gap-2.5 border-b border-border px-5">
          <span className="grid size-7 place-items-center rounded-md bg-accent text-fg-on-accent shadow-xs">
            <Icon name="diagram" />
          </span>
          <div className="flex flex-col">
            <span className="type-subheading text-fg">Архитектор</span>
            <span className="type-caption text-fg-subtle">Дизайн-система</span>
          </div>
        </div>
        <ScrollArea className="flex-1">
          <nav aria-label="Разделы стайлгайда" className="flex flex-col gap-5 px-3 py-5">
            {NAV.map((group) => (
              <div key={group.group} className="flex flex-col gap-0.5">
                <span className="px-2 pb-1.5 type-caption text-fg-subtle">{group.group}</span>
                {group.items.map(([id, label]) => (
                  <a
                    key={id}
                    href={`#${id}`}
                    aria-current={active === id ? 'location' : undefined}
                    className={cn(
                      'relative rounded-md px-2 py-1.5 type-ui transition-colors duration-base',
                      active === id
                        ? 'bg-pressed text-fg'
                        : 'text-fg-muted hover:bg-hover hover:text-fg',
                    )}
                  >
                    {label}
                  </a>
                ))}
              </div>
            ))}
          </nav>
        </ScrollArea>
        <div className="flex items-center justify-between gap-2 border-t border-border px-5 py-3">
          <span className="type-caption text-fg-subtle">Тема</span>
          <ThemeSwitch compact />
        </div>
      </aside>

      <main className="min-w-0 flex-1">
        <header className="sticky top-0 z-20 flex h-14 items-center justify-between gap-4 border-b border-border bg-bg/85 px-10 backdrop-blur-md">
          <div className="flex items-center gap-2 type-ui text-fg-muted">
            <span>Архитектор</span>
            <Icon name="chevron-right" size={14} className="text-fg-subtle" />
            <span className="text-fg">Дизайн-система</span>
          </div>
          <div className="flex items-center gap-3">
            <span className="flex items-center gap-1.5 type-caption text-fg-subtle">
              Команды <Kbd keys={['mod', 'k']} />
            </span>
            <ThemeSwitch />
          </div>
        </header>

        <div className="@container mx-auto w-full max-w-[76rem] px-10 pb-24 ultra:max-w-[88rem]">
          <div className="grid items-center gap-10 border-b border-border py-14 @5xl:grid-cols-[1fr_26rem]">
            <div className="flex flex-col gap-5">
              <div className="flex flex-wrap gap-2">
                <Badge tone="accent" variant="outline">
                  Geist и Geist Mono
                </Badge>
                <Badge variant="outline">OKLCH</Badge>
                <Badge tone="success" variant="outline" icon="check">
                  WCAG AA в обеих темах
                </Badge>
              </div>
              <h1 className="type-display max-w-2xl text-fg">Дизайн-система Архитектора</h1>
              <p className="type-body max-w-xl text-fg-muted">
                Токены, компоненты и правила, из которых собирается каждый экран. Здесь всё живое:
                наводите, нажимайте, переключайте тему. Подробные правила —
                docs/frontend/styleguide.md.
              </p>
            </div>
            <HeroComposition />
          </div>

          <PrinciplesSection />
          <PaletteSection />
          <TokensSection />
          <TypographySection />
          <SpacingSection />
          <SurfacesSection />
          <MotionSection />
          <IconsSection />
          <BrandSection />
          <ButtonsSection />
          <FieldsSection />
          <ChoiceSection />
          <OverlaysSection />
          <NavigationSection />
          <StatusSection />
          <FeedbackSection />
          <LayoutSection />
          <ExampleSection />
        </div>
      </main>
    </div>
  )
}
