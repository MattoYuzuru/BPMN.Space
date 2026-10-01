import { lintSource } from './design-lint.mjs'

const rules = (path, src) => lintSource(path, src).map((p) => p.rule)

describe('design-lint', () => {
  it('запрещает нативные контролы вне дизайн-системы', () => {
    expect(rules('src/features/a.tsx', '<button onClick={x}>Ок</button>')).toContain(
      'native-control',
    )
    expect(rules('src/features/a.tsx', '<input type="checkbox" />')).toContain('native-control')
    expect(rules('src/shared/ui/button/button.tsx', '<button />')).toEqual([])
  })

  it('запрещает сырые цвета', () => {
    expect(rules('src/features/a.tsx', "<div className='bg-[#ff0000]' />")).toContain('raw-color')
    expect(rules('src/features/a.css', 'a { color: rgb(1 2 3) }')).toContain('raw-color')
    expect(rules('src/features/a.tsx', "<div className='bg-accent text-fg' />")).toEqual([])
  })

  it('запрещает символы и эмодзи вместо иконок', () => {
    expect(rules('src/features/a.tsx', '<span>Далее →</span>')).toContain('pseudo-icon')
    expect(rules('src/features/a.tsx', "const s = 'Решено 2 · осталось 1'")).toContain(
      'pseudo-icon',
    )
    expect(rules('src/features/a.tsx', '<span>Готово ✅</span>')).toContain('pseudo-icon')
  })

  it('запрещает тире-заглушки, но не тире в тексте', () => {
    expect(rules('src/features/a.tsx', "value ?? '—'")).toContain('dash-placeholder')
    expect(rules('src/features/a.tsx', '<td>—</td>')).toContain('dash-placeholder')
    expect(rules('src/features/a.tsx', '<p>Договор — за 15 дней</p>')).toEqual([])
  })

  it('запрещает визуальные inline-стили, шрифты и системные диалоги', () => {
    expect(rules('src/features/a.tsx', '<div style={{ color: x }} />')).toContain(
      'inline-visual-style',
    )
    expect(rules('src/features/a.tsx', '<div style={{ width: w }} />')).toEqual([])
    expect(rules('src/features/a.css', 'a { font-family: Arial }')).toContain('raw-font')
    expect(rules('src/features/a.ts', 'if (confirm("Удалить?")) {}')).toContain('browser-dialog')
  })

  it('запрещает прокрутку мимо ScrollArea', () => {
    expect(rules('src/widgets/a.tsx', "<div className='h-full overflow-y-auto' />")).toContain(
      'raw-scroll',
    )
    expect(rules('src/widgets/a.tsx', '<div className="hover:overflow-scroll" />')).toContain(
      'raw-scroll',
    )
    expect(rules('src/widgets/a.css', '.x { overflow-x: auto }')).toContain('raw-scroll')
    expect(rules('src/widgets/a.tsx', "<div className='overflow-hidden' />")).toEqual([])
    expect(rules('src/shared/ui/dialog/dialog.tsx', "'overflow-y-auto'")).toEqual([])
  })

  it('запрещает браузерные подсказки title и SVG в разметке экранов', () => {
    expect(rules('src/features/a.tsx', '<span title="Удалить">x</span>')).toContain('native-title')
    expect(rules('src/features/a.tsx', '<EmptyState title="Пусто" icon="folder" />')).toEqual([])
    expect(rules('src/features/a.tsx', '<svg viewBox="0 0 16 16">')).toContain('inline-svg')
  })

  it('запрещает произвольные значения для визуальных свойств', () => {
    expect(rules('src/features/a.tsx', "<p className='text-[13px]' />")).toContain(
      'arbitrary-visual',
    )
    expect(rules('src/features/a.tsx', "<p className='hover:bg-[var(--x)]' />")).toContain(
      'arbitrary-visual',
    )
    expect(rules('src/features/a.tsx', "<p className='rounded-t-[3px] shadow-(--x)' />")).toContain(
      'arbitrary-visual',
    )
    expect(rules('src/features/a.tsx', "<p className='duration-[400ms]' />")).toContain(
      'arbitrary-visual',
    )
    expect(rules('src/features/a.tsx', "<p className='w-[22rem] text-sm rounded-md' />")).toEqual(
      [],
    )
    expect(rules('src/features/a.tsx', "<p className='data-[state=open]:bg-hover' />")).toEqual([])
  })

  it('пропускает строки с design-lint-ignore и чужие расширения', () => {
    expect(rules('src/features/a.tsx', '<button /> // design-lint-ignore')).toEqual([])
    expect(rules('src/features/a.md', '<button />')).toEqual([])
  })
})
