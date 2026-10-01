import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { gzipSync } from 'node:zlib'
import {
  checkBundle,
  collectStartupFiles,
  findStaticImports,
  parseEntryAssets,
} from './check-bundle.mjs'

const HTML = `<!doctype html><html><head>
<script type="module" crossorigin src="/assets/index-a1.js"></script>
<link rel="modulepreload" crossorigin href="/assets/vendor-b2.js">
<link rel="stylesheet" crossorigin href="/assets/index-c3.css">
<link rel="icon" href="/favicon.svg">
<script src="https://example.org/analytics.js"></script>
</head><body></body></html>`

let dist

function write(file, content) {
  mkdirSync(join(dist, file, '..'), { recursive: true })
  writeFileSync(join(dist, file), content)
}

beforeEach(() => {
  dist = mkdtempSync(join(tmpdir(), 'check-bundle-'))
  write('index.html', HTML)
  write(
    'assets/index-a1.js',
    'import{a as b}from"./shared-d4.js";import"./polyfill-e5.js";const l=()=>import("./editor-f6.js");',
  )
  write('assets/vendor-b2.js', 'export const v=1')
  write('assets/index-c3.css', '.app{color:red}')
  write('assets/shared-d4.js', 'export*from"./deep-g7.js";export const a=1')
  write('assets/polyfill-e5.js', '')
  write('assets/deep-g7.js', 'export const d=1')
  write('assets/editor-f6.js', 'const c="djs-container bjs-powered-by";')
})

afterEach(() => rmSync(dist, { recursive: true, force: true }))

describe('check-bundle', () => {
  it('берёт из index.html модульные скрипты, modulepreload и стили, но не внешние и не иконки', () => {
    expect(parseEntryAssets(HTML)).toEqual([
      'assets/index-a1.js',
      'assets/vendor-b2.js',
      'assets/index-c3.css',
    ])
  })

  it('различает статические и динамические импорты в минифицированном коде', () => {
    const code =
      'import{x as y}from"./a.js";import"./b.js";import * as z from \'./c.js\';' +
      'export*from"./d.js";export{q}from"./e.js";const l=()=>import("./lazy.js");' +
      'import{r}from"react";const s="import ./not-a-module";'
    expect(findStaticImports(code)).toEqual(['./a.js', './b.js', './c.js', './d.js', './e.js'])
  })

  it('собирает стартовые файлы рекурсивно и не заходит в ленивые чанки', () => {
    expect(collectStartupFiles(dist)).toEqual([
      'assets/deep-g7.js',
      'assets/index-a1.js',
      'assets/index-c3.css',
      'assets/polyfill-e5.js',
      'assets/shared-d4.js',
      'assets/vendor-b2.js',
    ])
  })

  it('считает gzip-размер стартовых файлов и проходит, если bpmn-js только в ленивом чанке', () => {
    const result = checkBundle(dist)
    const css = result.files.find((file) => file.file === 'assets/index-c3.css')
    expect(css).toMatchObject({
      bytes: 15,
      gzip: gzipSync('.app{color:red}').length,
      forbidden: [],
    })
    expect(result.files.map((file) => file.file)).not.toContain('assets/editor-f6.js')
    expect(result.total).toBe(result.files.reduce((sum, file) => sum + file.gzip, 0))
    expect(result.problems).toEqual([])
  })

  it('падает, если библиотека схем попала в стартовый бандл статическим импортом', () => {
    write('assets/index-a1.js', 'import"./editor-f6.js";')
    const { problems } = checkBundle(dist)
    expect(problems).toHaveLength(1)
    expect(problems[0]).toContain('assets/editor-f6.js')
    expect(problems[0]).toContain('diagram-js')
    expect(problems[0]).toContain('bpmn-js')
  })

  it('падает при превышении бюджета', () => {
    const { total, problems } = checkBundle(dist, 10)
    expect(total).toBeGreaterThan(10)
    expect(problems.join()).toContain('бюджет')
  })
})
