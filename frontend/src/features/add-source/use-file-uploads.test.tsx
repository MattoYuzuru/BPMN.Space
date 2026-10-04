import { QueryClientProvider } from '@tanstack/react-query'
import { act, renderHook, waitFor } from '@testing-library/react'
import type { ReactNode } from 'react'
import { queryClient } from '@/app/query-client'
import { onboardingKeys } from '@/entities/onboarding'
import { stubUploads } from '@/test/xhr'
import { useFileUploads } from './use-file-uploads'

vi.mock('@/shared/ui', async (original) => ({
  ...(await original<typeof import('@/shared/ui')>()),
  toast: Object.assign(vi.fn(), { success: vi.fn(), error: vi.fn() }),
}))

afterEach(() => {
  vi.unstubAllGlobals()
  queryClient.clear()
})

describe('загрузка файла и чек-лист', () => {
  it('после успешной загрузки (XHR) состояние онбординга перечитывается', async () => {
    stubUploads([
      {
        status: 201,
        body: {
          id: 's1',
          project_id: 'p1',
          kind: 'file',
          title: 'Записка.docx',
          status: 'processing',
        },
      },
    ])
    const key = onboardingKeys.user('u1')
    queryClient.setQueryData(key, { enabled: true })
    const wrapper = ({ children }: { children: ReactNode }) => (
      <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
    )
    const { result } = renderHook(() => useFileUploads('p1'), { wrapper })
    act(() => result.current.upload([new File(['текст'], 'Записка.docx')]))
    await waitFor(() => expect(queryClient.getQueryState(key)?.isInvalidated).toBe(true))
  })
})
