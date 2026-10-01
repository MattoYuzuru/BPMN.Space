#!/usr/bin/env node
/**
 * check-bundle — бюджет стартового бандла после `vite build`.
 *
 * Стартовый бандл — то, что браузер обязан скачать до первого экрана: скрипты и стили из dist/index.html
 * плюс всё, что entry подтягивает статическими импортами (рекурсивно). Динамические import() —
 * ленивые чанки маршрутов и редактора BPMN — сюда не входят.
 *
 * Проверки:
 *  1. В стартовых файлах нет bpmn-js, diagram-js и их плагинов (ищем по CSS-классам, которые
 *     есть только в этих библиотеках: имена модулей после минификации не сохраняются).
 *  2. Суммарный размер стартовых JS и CSS после gzip не больше бюджета.
 *
 * Почему 200 КБ gzip: React 19 + ReactDOM ≈ 60 КБ, TanStack Router ≈ 30 КБ, TanStack Query ≈ 13 КБ,
 * примитивы Radix на каркасе ≈ 20 КБ, motion ≈ 20 КБ, sonner, zustand, openapi-fetch ≈ 15 КБ,
 * стили Tailwind ≈ 15 КБ — около 175 КБ на полностью собранном каркасе, плюс запас ~15 %.
 * На медленном корпоративном канале (≈ 1,6 Мбит/с) 200 КБ — около секунды загрузки, в пределах
 * распространённого ориентира 130–170 КБ «критического» JS на средний ноутбук с запасом под CSS.
 * Один только bpmn-js с плагинами весит ≈ 470 КБ gzip — он обязан оставаться ленивым.
 *
 * Запуск: `node scripts/check-bundle.mjs [dist]` (по умолчанию frontend/dist). Входит в `make build`.
 */
import { existsSync, readFileSync } from 'node:fs'
import { dirname, join, normalize, relative, resolve, sep } from 'node:path'
import { gzipSync } from 'node:zlib'

const ROOT = import.meta.dirname ? resolve(import.meta.dirname, '..') : process.cwd()

export const BUDGET_GZIP_BYTES = 200 * 1024

/** Классы, которые встречаются только в коде и стилях соответствующих библиотек. */
export const FORBIDDEN_SIGNATURES = [
  { library: 'diagram-js', signature: 'djs-container' },
  { library: 'bpmn-js', signature: 'bjs-container' },
  { library: 'bpmn-js (водяной знак)', signature: 'bjs-powered-by' },
  { library: 'bpmn-js-properties-panel', signature: 'bio-properties-panel' },
  { library: 'bpmn-js-token-simulation', signature: 'bts-container' },
  { library: 'diagram-js-minimap', signature: 'djs-minimap' },
]

/** Скрипты модулей, modulepreload и стили из index.html (пути относительно dist). */
export function parseEntryAssets(html) {
  const assets = []
  for (const tag of html.match(/<(script|link)\b[^>]*>/gi) ?? []) {
    const attr = (name) => new RegExp(`\\s${name}=["']([^"']+)["']`, 'i').exec(tag)?.[1]
    if (/^<script/i.test(tag)) {
      const src = attr('src')
      if (src && attr('type') === 'module') assets.push(src)
    } else {
      const rel = attr('rel')
      const href = attr('href')
      if (href && (rel === 'stylesheet' || rel === 'modulepreload')) assets.push(href)
    }
  }
  return assets.filter((url) => !/^(https?:)?\/\//.test(url)).map((url) => url.replace(/^\//, ''))
}

/**
 * Спецификаторы статических импортов и реэкспортов из (минифицированного) ES-модуля:
 * `import"./a.js"`, `import{a as b}from"./a.js"`, `export*from"./a.js"`. Динамический `import(…)` — нет.
 */
export function findStaticImports(code) {
  const pattern = /(?:^|[^\w$.])(?:import|export)\s*(?:[\w$*{}\s,]*?\s*from\s*)?(["'])([^"'\n]+)\1/g
  return [...code.matchAll(pattern)]
    .map((match) => match[2])
    .filter((spec) => /^\.{0,2}\//.test(spec))
}

/** Стартовые файлы: ресурсы index.html и замыкание по статическим импортам JS. */
export function collectStartupFiles(distDir) {
  const html = readFileSync(join(distDir, 'index.html'), 'utf8')
  const queue = parseEntryAssets(html)
  const seen = new Set()
  while (queue.length) {
    const file = normalize(queue.shift())
    if (seen.has(file) || !existsSync(join(distDir, file))) continue
    seen.add(file)
    if (!file.endsWith('.js')) continue
    const code = readFileSync(join(distDir, file), 'utf8')
    for (const spec of findStaticImports(code)) {
      const target = spec.startsWith('/') ? spec.slice(1) : join(dirname(file), spec)
      queue.push(relative(distDir, resolve(distDir, target)))
    }
  }
  return [...seen].map((file) => file.split(sep).join('/')).sort()
}

/** Размеры и найденные сигнатуры запрещённых библиотек по каждому стартовому файлу. */
export function inspectFiles(distDir, files) {
  return files.map((file) => {
    const content = readFileSync(join(distDir, file))
    const text = content.toString('utf8')
    return {
      file,
      bytes: content.length,
      gzip: gzipSync(content).length,
      forbidden: FORBIDDEN_SIGNATURES.filter(({ signature }) => text.includes(signature)).map(
        ({ library }) => library,
      ),
    }
  })
}

export function checkBundle(distDir, budget = BUDGET_GZIP_BYTES) {
  const files = inspectFiles(distDir, collectStartupFiles(distDir))
  const total = files.reduce((sum, file) => sum + file.gzip, 0)
  const problems = []
  for (const file of files) {
    if (file.forbidden.length)
      problems.push(`${file.file}: в стартовом бандле ${file.forbidden.join(', ')}`)
  }
  if (files.length === 0) problems.push('в index.html не найдено ни одного скрипта или стиля')
  if (total > budget) problems.push(`стартовый бандл ${kb(total)} gzip, бюджет ${kb(budget)}`)
  return { files, total, budget, problems }
}

function kb(bytes) {
  return `${(bytes / 1024).toFixed(1)} КБ`
}

function main(argv) {
  const distDir = resolve(argv[0] ?? join(ROOT, 'dist'))
  if (!existsSync(join(distDir, 'index.html'))) {
    console.error(`check-bundle: нет ${join(distDir, 'index.html')} — сначала vite build`)
    process.exit(1)
  }
  const { files, total, budget, problems } = checkBundle(distDir)
  console.log('Стартовый бандл (index.html и статические импорты):')
  for (const file of files)
    console.log(`  ${file.file.padEnd(48)} ${kb(file.gzip).padStart(10)} gzip`)
  console.log(`  ${'итого'.padEnd(48)} ${kb(total).padStart(10)} из ${kb(budget)}`)
  if (problems.length) {
    for (const problem of problems) console.error(`check-bundle: ${problem}`)
    process.exit(1)
  }
  console.log('check-bundle: ок — bpmn-js и плагины только в ленивых чанках')
}

if (import.meta.filename && process.argv[1] && resolve(process.argv[1]) === import.meta.filename) {
  main(process.argv.slice(2))
}
