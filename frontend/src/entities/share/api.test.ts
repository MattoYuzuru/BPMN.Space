import { QueryClient } from '@tanstack/react-query'
import type { ProjectDetail } from '@/entities/project'
import { stubApi } from '@/test/api-stub'
import { shareVersionSource } from './api'

const latest = {
  id: 'v-3',
  number: 3,
  project_id: 'p-1',
  origin: 'generated',
  created_at: '2026-10-01T10:00:00Z',
  diff: { added: 1, removed: 0, changed: 0 },
  report: { xsd_valid: true, lint: [], assumptions: [] },
  trace: {},
  lanes: [],
}
const detail = { id: 'p-1', latest_version: latest } as unknown as ProjectDetail

afterEach(() => vi.unstubAllGlobals())

describe('shareVersionSource', () => {
  it('собирает версию из ответа по ссылке и XML по пути ссылки', async () => {
    const calls = stubApi({
      'GET /api/v1/shares/tok/versions/v-3/xml': { text: '<definitions/>' },
    })
    const source = shareVersionSource('tok', detail)
    const client = new QueryClient()
    const version = await client.fetchQuery(source.detail('v-3') as never)
    expect(version).toMatchObject({ id: 'v-3', xml: '<definitions/>', number: 3 })
    expect(calls.map((call) => call.path)).toEqual(['/api/v1/shares/tok/versions/v-3/xml'])
  })

  it('истории нет: список — только последняя версия, скачивание — по пути ссылки', async () => {
    const source = shareVersionSource('tok', detail)
    expect(source.history).toBe(false)
    expect(source.xmlUrl('v-3')).toBe('/api/v1/shares/tok/versions/v-3/xml')
    const client = new QueryClient()
    const list = await client.fetchQuery(source.list('p-1') as never)
    expect(list).toEqual([latest])
  })

  it('чужую версию по ссылке не открывает', async () => {
    stubApi({})
    const source = shareVersionSource('tok', detail)
    const client = new QueryClient()
    await expect(client.fetchQuery(source.detail('v-1') as never)).rejects.toThrow()
  })
})
