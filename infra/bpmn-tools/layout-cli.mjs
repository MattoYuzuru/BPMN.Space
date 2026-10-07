import { readFile } from 'node:fs/promises'
import { layout } from './tools.mjs'

const result = await layout(await readFile(process.argv[2], 'utf8'))
for (const warning of result.warnings) process.stderr.write(`${warning}\n`)
process.stdout.write(result.xml)
