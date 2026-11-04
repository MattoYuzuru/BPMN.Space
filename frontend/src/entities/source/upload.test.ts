import type { Schemas } from '@/shared/api/client'
import { uploadFileSource } from './api'

const captured = vi.hoisted(() => ({ form: null as FormData | null }))

vi.mock('@/shared/api/client', async (original) => ({
  ...(await original<typeof import('@/shared/api/client')>()),
  postForm: vi.fn(async (_url: string, form: FormData) => {
    captured.form = form
    return { id: 's1', title: 'встреча.mp4' } as Schemas['Source']
  }),
}))

it('передаёт media_profile в multipart записи', async () => {
  await uploadFileSource('p1', {
    file: new File(['x'], 'встреча.mp4', { type: 'video/mp4' }),
    title: 'Встреча',
    mediaProfile: 'detailed',
  })
  expect(captured.form?.get('file')).toBeInstanceOf(File)
  expect(captured.form?.get('media_profile')).toBe('detailed')
  expect(captured.form?.get('title')).toBe('Встреча')
})
