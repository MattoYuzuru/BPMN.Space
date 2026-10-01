#!/usr/bin/env node
/**
 * design-lint — детерминированная проверка правил дизайн-системы (docs/frontend/styleguide.md).
 *
 * Запуск: `node scripts/design-lint.mjs [файлы...]`. Без аргументов проверяет весь `src/`.
 * Правила не применяются внутри дизайн-системы (`src/shared/ui`, `src/shared/styles`),
 * к сгенерированным файлам и тестам — там нативные элементы и сырые значения допустимы.
 */
import { readdirSync, readFileSync, statSync } from 'node:fs'
import { extname, join, relative, resolve, sep } from 'node:path'

// import.meta.dirname есть в Node; в окружении тестов (jsdom) его нет — там используется cwd.
const ROOT = import.meta.dirname ? resolve(import.meta.dirname, '..') : process.cwd()
const SRC = join(ROOT, 'src')
const EXTENSIONS = new Set(['.ts', '.tsx', '.css'])

/** Пути (относительно frontend/), где правила не действуют. */
const EXEMPT = [
  /^src\/shared\/ui\//,
  /^src\/shared\/styles\//,
  /\.gen\.ts$/,
  /\.test\.tsx?$/,
  /^src\/test\//,
]

/** Символы, которыми агенты любят заменять иконки. Иконки — только из Tabler через <Icon>. */
const PSEUDO_ICONS = '→←↑↓↔⟶⟵➜➔➝▶▸►▷◀◂◄▼▾▽▲▴△•·●○◦✓✔✗✘✕✖×★☆♦◆◇■□▪▫'

export const RULES = [
  {
    id: 'native-control',
    message:
      'Нативный элемент управления. Используй компоненты из @/shared/ui (Button, IconButton, Input, Textarea, Checkbox, Radio, Select, Switch).',
    test: (line, ext) => ext === '.tsx' && /<(button|input|select|textarea|option)\b/.test(line),
  },
  {
    id: 'raw-color',
    message:
      'Сырой цвет. Только токены дизайн-системы (классы bg-*, text-*, border-* или var(--…)).',
    test: (line) =>
      /(^|[^&\w])#[0-9a-fA-F]{3,8}\b/.test(line) ||
      /\b(rgba?|hsla?|oklch|oklab|lab|lch|color-mix)\(/.test(line) ||
      /-\[(#|rgb|hsl|oklch)/.test(line),
  },
  {
    id: 'pseudo-icon',
    message: 'Символ вместо иконки или эмодзи. Используй <Icon name="…" /> из @/shared/ui/icon.',
    test: (line, ext) => {
      if (ext === '.css') return false
      const code = line.replace(/\/\/.*$|\/\*.*?\*\//g, '')
      return (
        [...PSEUDO_ICONS].some((ch) => code.includes(ch)) || /\p{Extended_Pictographic}/u.test(code)
      )
    },
  },
  {
    id: 'dash-placeholder',
    message:
      'Тире-заглушка вместо пустого значения. Покажи осмысленное пустое состояние (EmptyState) или скрой поле.',
    test: (line, ext) =>
      ext !== '.css' && (/(['"`])\s*[—–]\s*\1/.test(line) || />\s*[—–-]\s*</.test(line)),
  },
  {
    id: 'inline-visual-style',
    message:
      'Визуальные свойства в style={{…}}. Цвет, фон, шрифт, тень и радиус задаются классами-токенами.',
    test: (line, ext) =>
      ext === '.tsx' &&
      /style=\{\{[^}]*\b(color|background|font|boxShadow|borderRadius|border)\b/.test(line),
  },
  {
    id: 'raw-font',
    message: 'Шрифт задаётся только токенами (font-sans, font-mono).',
    test: (line) => /font-family\s*:/.test(line) || /font-\[['"]/.test(line),
  },
  {
    id: 'raw-scroll',
    message:
      'Прокрутка через overflow-auto/scroll. Используй <ScrollArea> из @/shared/ui — единый тонкий скроллбар.',
    test: (line, ext) =>
      ext === '.css'
        ? /overflow(-[xy])?\s*:\s*(auto|scroll)\b/.test(line)
        : /(^|[\s"'`:!])overflow(-[xy])?-(auto|scroll)\b/.test(line),
  },
  {
    id: 'native-title',
    message:
      'Атрибут title на элементе даёт браузерную подсказку. Используй <Tooltip> из @/shared/ui.',
    test: (line, ext) => ext === '.tsx' && /<[a-z][\w.-]*\b[^>]*\stitle=/.test(line),
  },
  {
    id: 'inline-svg',
    message: 'SVG в разметке экрана. Иконки — <Icon name="…" />, графика — компонент в shared/ui.',
    test: (line, ext) => ext === '.tsx' && /<svg\b/.test(line),
  },
  {
    id: 'arbitrary-visual',
    message:
      'Произвольное значение для цвета, шрифта, радиуса, тени или движения. Только токены: text-sm, rounded-md, shadow-md, ease-soft.',
    test: (line) =>
      /(^|[\s"'`:!])(text|bg|border|ring|outline|shadow|rounded(-[a-z]+)?|font|leading|tracking|fill|stroke|from|via|to|decoration|duration|ease|delay)-[[(]/.test(
        line,
      ),
  },
  {
    id: 'browser-dialog',
    message: 'Системные alert/confirm/prompt запрещены. Используй Dialog или toast из @/shared/ui.',
    test: (line, ext) => ext !== '.css' && /\b(window\.)?(alert|confirm|prompt)\(/.test(line),
  },
]

function walk(dir) {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name)
    return statSync(path).isDirectory() ? walk(path) : [path]
  })
}

/** Проверяет текст файла и возвращает нарушения. Экспортируется для тестов. */
export function lintSource(relPath, source) {
  const ext = extname(relPath)
  if (!EXTENSIONS.has(ext) || EXEMPT.some((re) => re.test(relPath))) return []
  const problems = []
  source.split('\n').forEach((line, index) => {
    if (line.includes('design-lint-ignore')) return
    for (const rule of RULES) {
      if (rule.test(line, ext))
        problems.push({ file: relPath, line: index + 1, rule: rule.id, message: rule.message })
    }
  })
  return problems
}

function main(argv) {
  const files = argv.length
    ? argv.map((f) => resolve(process.cwd(), f)).filter((f) => f.startsWith(SRC + sep))
    : walk(SRC)
  const problems = files.flatMap((file) => {
    const rel = relative(ROOT, file).split(sep).join('/')
    try {
      return lintSource(rel, readFileSync(file, 'utf8'))
    } catch {
      return []
    }
  })
  for (const p of problems) console.error(`${p.file}:${p.line}  [${p.rule}]  ${p.message}`)
  if (problems.length) {
    console.error(
      `\ndesign-lint: нарушений — ${problems.length}. Правила: docs/frontend/styleguide.md`,
    )
    process.exit(1)
  }
}

if (import.meta.filename && process.argv[1] && resolve(process.argv[1]) === import.meta.filename) {
  main(process.argv.slice(2))
}
