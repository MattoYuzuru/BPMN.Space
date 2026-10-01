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

  it('пропускает строки с design-lint-ignore и чужие расширения', () => {
    expect(rules('src/features/a.tsx', '<button /> // design-lint-ignore')).toEqual([])
    expect(rules('src/features/a.md', '<button />')).toEqual([])
  })
})
